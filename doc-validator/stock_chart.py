import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import FinanceDataReader as fdr


def parse_csv(file) -> pd.DataFrame:
    try:
        filename = file.name if hasattr(file, "name") else str(file)

        dtype_map = {
            '주식이름': str,
            '주식번호': str
        }

        # ✅ 파일 읽기 (CSV 인코딩 대응)
        if filename.endswith(".csv"):
            try:
                df = pd.read_csv(file, dtype=dtype_map, encoding='utf-8')
            except:
                file.seek(0)
                df = pd.read_csv(file, dtype=dtype_map, encoding='cp949')

        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(file, dtype=dtype_map)

        else:
            raise ValueError("지원하지 않는 파일 형식입니다. (csv, xlsx만 가능)")

        # ✅ 컬럼명 공백 제거 (엑셀에서 자주 터짐)
        df.columns = df.columns.str.strip()

        required_columns = ['주식이름', '주식번호', '구매금액', '판매금액', '날짜']
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"필수 컬럼 '{col}'이(가) 없습니다.")

        df['주식이름'] = df['주식이름'].astype(str).str.strip()
        df['주식번호'] = df['주식번호'].astype(str).str.strip().str.zfill(6)

        df['구매금액'] = pd.to_numeric(df['구매금액'], errors='coerce')
        df['판매금액'] = pd.to_numeric(df['판매금액'], errors='coerce')

        df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce')

        df = df.dropna(subset=['날짜', '주식번호'])
        df = df.sort_values('날짜')

        return df.reset_index(drop=True)

    except Exception as e:
        raise ValueError(f"파일 파싱 오류: {str(e)}")


def get_stock_chart_data(stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        # 🔥 날짜도 통일
        start_date = pd.to_datetime(start_date)
        end_date = pd.to_datetime(end_date)

        df = fdr.DataReader(stock_code, start=start_date, end=end_date)
        df = df.reset_index()

        # ❌ 제거: .dt.date
        df['Date'] = pd.to_datetime(df['Date'])  # Timestamp 유지

        return df

    except Exception as e:
        raise ValueError(f"주식 데이터 조회 오류: {str(e)}")

def create_stock_chart(stock_df: pd.DataFrame, transaction_df: pd.DataFrame, stock_name: str) -> go.Figure:
    fig = go.Figure()
    
    fig.add_trace(go.Candlestick(
        x=stock_df['Date'],
        open=stock_df['Open'],
        high=stock_df['High'],
        low=stock_df['Low'],
        close=stock_df['Close'],
        name='주가',
        increasing_line_color='#26a69a',
        decreasing_line_color='#ef5350'
    ))
    
    fig.add_trace(go.Scatter(
        x=stock_df['Date'],
        y=stock_df['Close'],
        mode='lines',
        name='收盘价',
        line=dict(color='#2196F3', width=1)
    ))
    
    buy_transactions = transaction_df[transaction_df['구매금액'].notna() & (transaction_df['구매금액'] > 0)]
    if not buy_transactions.empty:
        fig.add_trace(go.Scatter(
            x=buy_transactions['날짜'],
            y=[stock_df[stock_df['Date'] <= date]['Close'].iloc[-1] 
               if not stock_df[stock_df['Date'] <= date].empty else None 
               for date in buy_transactions['날짜']],
            mode='markers',
            name='구매',
            marker=dict(
                color='#2196F3',
                size=15,
                symbol='triangle-up',
                line=dict(color='white', width=2)
            ),
            text=[f"구매: {row['구매금액']:,.0f}원" for _, row in buy_transactions.iterrows()],
            hoverinfo='text+x'
        ))
    
    sell_transactions = transaction_df[transaction_df['판매금액'].notna() & (transaction_df['판매금액'] > 0)]
    if not sell_transactions.empty:
        fig.add_trace(go.Scatter(
            x=sell_transactions['날짜'],
            y=[stock_df[stock_df['Date'] <= date]['Close'].iloc[-1] 
               if not stock_df[stock_df['Date'] <= date].empty else None 
               for date in sell_transactions['날짜']],
            mode='markers',
            name='판매',
            marker=dict(
                color='#EF5350',
                size=15,
                symbol='triangle-down',
                line=dict(color='white', width=2)
            ),
            text=[f"판매: {row['판매금액']:,.0f}원" for _, row in sell_transactions.iterrows()],
            hoverinfo='text+x'
        ))
    
    fig.update_layout(
        title=dict(
            text=f'{stock_name} 차트',
            font=dict(size=20)
        ),
        xaxis_title='날짜',
        yaxis_title='주가 (원)',
        hovermode='x unified',
        template='plotly_white',
        height=600,
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1
        )
    )
    
    return fig


def get_unique_stocks(df: pd.DataFrame) -> list:
    return df['주식이름'].unique().tolist()


def filter_transactions_by_stock(df: pd.DataFrame, stock_name: str) -> pd.DataFrame:
    return df[df['주식이름'] == stock_name].copy()
