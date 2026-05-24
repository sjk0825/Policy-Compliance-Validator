import pandas as pd
import plotly.graph_objects as go
from typing import Optional
from datetime import datetime, timedelta
from .base import BaseTool, ToolResult, ToolDefinition, ToolCapability


class StockChartTool(BaseTool):
    def __init__(self):
        super().__init__()

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="stock_chart",
            description="주식 차트를 조회합니다. 주식번호(티커) 또는 회사명을 입력하면 캔들스틱 차트를 생성합니다.",
            capabilities=[ToolCapability.STOCK_CHART],
            parameters={
                "required": ["stock_code"],
                "properties": {
                    "stock_code": {"type": "string", "description": "주식 종목코드 (예: 005930 삼성전자, AAPL 애플)"},
                    "stock_name": {"type": "string", "description": "주식 이름 (차트 제목용, 선택사항)"},
                    "days": {"type": "integer", "description": "조회할 기간(일)", "default": 90}
                }
            }
        )

    def execute(self, stock_code: str, stock_name: str = "", days: int = 90) -> ToolResult:
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            df = self._fetch_data(stock_code, start_date, end_date)
            if df.empty:
                return ToolResult(success=False, error=f"'{stock_code}' 데이터를 찾을 수 없습니다.")

            chart_html = self._create_chart(df, stock_code, stock_name or stock_code)
            summary = self._get_summary(df, stock_code, stock_name or stock_code)

            return ToolResult(
                success=True,
                data={
                    "html": chart_html,
                    "summary": summary,
                    "stock_code": stock_code,
                    "stock_name": stock_name or stock_code,
                    "data_points": len(df)
                },
                metadata={
                    "tool": "stock_chart",
                    "action": "chart",
                    "stock_code": stock_code,
                    "data_points": len(df)
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _fetch_data(self, stock_code: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        import FinanceDataReader as fdr
        df = fdr.DataReader(stock_code, start=start_date, end=end_date)
        df = df.reset_index()
        date_col = 'Date' if 'Date' in df.columns else df.columns[0]
        df['Date'] = pd.to_datetime(df[date_col])
        if date_col != 'Date':
            df = df.drop(columns=[date_col])
        col_map = {}
        for c in df.columns:
            c_lower = c.lower().strip()
            if c_lower == 'open': col_map[c] = 'Open'
            elif c_lower == 'high': col_map[c] = 'High'
            elif c_lower == 'low': col_map[c] = 'Low'
            elif c_lower == 'close': col_map[c] = 'Close'
            elif c_lower == 'volume': col_map[c] = 'Volume'
        df = df.rename(columns=col_map)
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col not in df.columns:
                df[col] = 0
        return df

    def _create_chart(self, df: pd.DataFrame, stock_code: str, stock_name: str) -> str:
        fig = go.Figure()

        fig.add_trace(go.Candlestick(
            x=df['Date'],
            open=df['Open'],
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            name='주가',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350'
        ))

        fig.add_trace(go.Scatter(
            x=df['Date'],
            y=df['Close'],
            mode='lines',
            name='종가',
            line=dict(color='#2196F3', width=1)
        ))

        # volume bars
        fig.add_trace(go.Bar(
            x=df['Date'],
            y=df['Volume'],
            name='거래량',
            yaxis='y2',
            marker=dict(color='rgba(100,100,100,0.3)')
        ))

        fig.update_layout(
            title=dict(text=f'{stock_name} ({stock_code}) 주가 차트', font=dict(size=18)),
            xaxis_title='날짜',
            yaxis_title='주가',
            hovermode='x unified',
            template='plotly_white',
            height=500,
            xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            yaxis2=dict(
                title='거래량',
                overlaying='y',
                side='right',
                showgrid=False,
                visible=False
            )
        )

        return fig.to_html(include_plotlyjs='cdn', full_html=False)

    def _get_summary(self, df: pd.DataFrame, stock_code: str, stock_name: str) -> str:
        latest = df.iloc[-1]
        prev = df.iloc[0]
        change = latest['Close'] - prev['Close']
        change_pct = (change / prev['Close']) * 100

        return (
            f"{stock_name}({stock_code}) 주가 정보\n"
            f"기간: {df['Date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['Date'].iloc[-1].strftime('%Y-%m-%d')}\n"
            f"최근 종가: {latest['Close']:,.0f}원\n"
            f"변동: {change:+,.0f}원 ({change_pct:+.2f}%)\n"
            f"최고: {df['High'].max():,.0f}원 / 최저: {df['Low'].min():,.0f}원\n"
            f"평균 거래량: {df['Volume'].mean():,.0f}"
        )
