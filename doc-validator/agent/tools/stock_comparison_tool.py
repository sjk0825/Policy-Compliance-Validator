import pandas as pd
import plotly.graph_objects as go
from typing import List, Tuple
from datetime import datetime, timedelta
from .base import BaseTool, ToolResult, ToolDefinition, ToolCapability
from .stock_chart_tool import fetch_stock_data


COLORS = ['#2196F3', '#EF5350', '#4CAF50', '#FF9800', '#9C27B0',
          '#00BCD4', '#E91E63', '#3F51B5', '#8BC34A', '#FF5722']


class StockComparisonTool(BaseTool):
    def __init__(self):
        super().__init__()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="stock_comparison",
            description="여러 주식의 주가를 비교한 겹쳐진(overlay) 차트를 생성합니다. 종목코드나 회사명을 여러 개 입력하면 수익률 기준으로 비교합니다.",
            capabilities=[ToolCapability.STOCK_CHART],
            parameters={
                "required": ["stock_codes"],
                "properties": {
                    "stock_codes": {"type": "array", "description": "비교할 주식 종목코드/이름 리스트 (예: ['005930', 'AAPL'])"},
                    "stock_names": {"type": "array", "description": "주식 이름 리스트 (차트 범례용, 선택사항)"},
                    "days": {"type": "integer", "description": "조회할 기간(일)", "default": 90}
                }
            }
        )

    def execute(self, stock_codes: List[str], stock_names: List[str] = None,
                days: int = 90) -> ToolResult:
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            if not stock_codes or len(stock_codes) < 2:
                return ToolResult(success=False, error="비교할 종목을 2개 이상 입력해주세요.")

            names = stock_names or []
            while len(names) < len(stock_codes):
                names.append("")

            results: List[Tuple[str, str, pd.DataFrame]] = []
            for i, code in enumerate(stock_codes):
                df = fetch_stock_data(code, start_date, end_date)
                if df.empty:
                    return ToolResult(success=False, error=f"'{code}' 데이터를 찾을 수 없습니다.")
                name = names[i] or code
                results.append((code, name, df))

            chart_html = self._create_comparison_chart(results)
            summary = self._get_comparison_summary(results)

            return ToolResult(
                success=True,
                data={
                    "html": chart_html,
                    "summary": summary,
                    "stock_count": len(results),
                    "stock_codes": stock_codes,
                    "stock_names": [n for _, n, _ in results],
                    "days": days
                },
                metadata={
                    "tool": "stock_comparison",
                    "action": "compare",
                    "stock_codes": stock_codes,
                    "stock_count": len(results)
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _create_comparison_chart(self, results: List[Tuple[str, str, pd.DataFrame]]) -> str:
        fig = go.Figure()

        for i, (code, name, df) in enumerate(results):
            first_close = df['Close'].iloc[0]
            df = df.copy()
            df['pct_change'] = ((df['Close'] - first_close) / first_close) * 100

            color = COLORS[i % len(COLORS)]
            fig.add_trace(go.Scatter(
                x=df['Date'],
                y=df['pct_change'],
                mode='lines',
                name=f'{name} ({code})',
                line=dict(color=color, width=2)
            ))

            latest = df['Close'].iloc[-1]
            latest_pct = ((latest - first_close) / first_close) * 100
            last_date = df['Date'].iloc[-1]
            fig.add_annotation(
                x=last_date,
                y=latest_pct,
                text=f"{latest_pct:+.1f}%",
                showarrow=False,
                yshift=10,
                font=dict(color=color, size=11)
            )

        fig.update_layout(
            title=dict(text='주가 수익률 비교 (%)', font=dict(size=18)),
            xaxis_title='날짜',
            yaxis_title='수익률 (%)',
            hovermode='x unified',
            template='plotly_white',
            height=500,
            xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )

        return fig.to_html(include_plotlyjs='cdn', full_html=False)

    def _get_comparison_summary(self, results: List[Tuple[str, str, pd.DataFrame]]) -> str:
        lines = [f"주가 수익률 비교 (기간: ~{results[0][2]['Date'].iloc[-1].strftime('%Y-%m-%d')})"]
        for code, name, df in results:
            first = df['Close'].iloc[0]
            latest = df['Close'].iloc[-1]
            change_pct = ((latest - first) / first) * 100
            high = df['High'].max()
            low = df['Low'].min()
            lines.append(
                f"  {name}({code}): {change_pct:+.2f}% "
                f"(최고 {high:,.0f} / 최저 {low:,.0f})"
            )
        return "\n".join(lines)
