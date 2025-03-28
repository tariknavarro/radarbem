import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import numpy as np
import requests
import json
from datetime import datetime, timedelta
import hmac
import hashlib
import base64

# Configurações da página
st.set_page_config(
    page_title="Radar do Mercado | Bem Energia",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Título principal e autor
TITLE = "📊 Radar do Mercado | Bem Energia"
AUTHOR = "Tárik Navarro"

# Credenciais de login
LOGIN_USERNAME = "bemenergia"
LOGIN_PASSWORD = "bem@2025"

# Variáveis globais
ambiente = 'https://api-ehub.bbce.com.br/'
blacklist_produtos = [
    "SE CON MEN SET/24 - Preço Fixo",
    "SE CON MEN OUT/24 - Preço Fixo",
    "SE CON TRI OUT/24 DEZ/24 - Preço Fixo",
    # Adicione outros produtos a serem ignorados aqui
]

# Função para verificar login
def check_password():
    """Retorna `True` se as credenciais estão corretas."""
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.password = ""

    if st.session_state.logged_in:
        return True

    # Primeira execução, mostra formulário de login
    st.title("Login para Radar do Mercado")
    
    # Adicionar logo ou imagem
    st.markdown("### Bem Energia")
    
    # Criar caixas de login
    username = st.text_input("Usuário", key="username_input")
    password = st.text_input("Senha", type="password", key="password_input")
    
    if st.button("Login"):
        if username == LOGIN_USERNAME and password == LOGIN_PASSWORD:
            st.session_state.logged_in = True
            st.session_state.username = username
            st.session_state.password = password
            return True
        else:
            st.error("Usuário ou senha incorretos")
            return False
    
    return False

# Função de login na API para obter o token
def loginAPInew(cod, email, password, apiKey):
    url = ambiente + "bus/v2/login"
    response = requests.post(url, headers={'Content-Type': 'application/json', 'apiKey': apiKey},
                           data=json.dumps({"companyExternalCode": cod, "email": email, "password": password}))
    response_json = response.json()
    return [response_json["userId"], response_json["idToken"], response_json["companyId"]]

# Função para renovar o token quando expira
def refrehToken(token, refreshToken, apiKey):
    url = ambiente + "bus/v1/refresh-token"
    response = requests.post(url, headers={'Content-Type': 'application/json',
                                         'Authorization': 'Bearer ' + token, 'apiKey': apiKey},
                           data=json.dumps({'refreshToken': refreshToken}))
    response_json = response.json()

    if 'idToken' in response_json:
        return response_json["idToken"]
    else:
        st.error(f"Erro ao renovar token: {response_json.get('message', 'Erro desconhecido')}")
        return None

def negotiabletickers(token, apiKey, wallet):
    url = ambiente+"bus/v1/negotiable-tickers?walletId="+str(wallet)
    response = requests.request("GET", url, headers={'Accept': 'application/json','Authorization': 'Bearer '+token,'apiKey': apiKey}, data={})
    if response.status_code != 200:
        token = refrehToken(token, refreshToken, apiKey)
        response = requests.request("GET", url, headers={'Accept': 'application/json','Authorization': 'Bearer '+token,'apiKey': apiKey}, data={})
    return json.loads(response.text)['tickers']

def wallet(token, apiKey):
    url = ambiente+"bus/v1/wallets"
    response = requests.request("GET", url, headers={'Accept': 'application/json','Authorization': 'Bearer '+token,'apiKey': apiKey}, data={})
    if response.status_code != 200:
        token = refrehToken(token, refreshToken, apiKey)
        response = requests.request("GET", url, headers={'Accept': 'application/json','Authorization': 'Bearer '+token,'apiKey': apiKey}, data={})
    return json.loads(response.text)[0]['id']

# Função para buscar negócios da plataforma entre duas datas e carregar em um DataFrame
@st.cache_data(ttl=3600)  # Cache por 1 hora
def carregar_base_dados(token, apiKey, DataRef1, DataRef2, refreshToken):
    url = ambiente + "bus/v1/all-deals/report?initialPeriod=" + DataRef1 + "&finalPeriod=" + DataRef2
    response = requests.get(url, headers={'Accept': 'application/json', 'Authorization': 'Bearer ' + token, 'apiKey': apiKey})
    if response.status_code != 200:
        token = refrehToken(token, refreshToken, apiKey)
        response = requests.get(url, headers={'Accept': 'application/json', 'Authorization': 'Bearer ' + token, 'apiKey': apiKey})

    # Carregar todos os negócios em um DataFrame
    df = pd.DataFrame(response.json())

    # Convertendo a coluna 'createdAt' para datetime e setando como índice
    df['createdAt'] = pd.to_datetime(df['createdAt'])
    df.set_index('createdAt', inplace=True)

    return df

# Função para mapear description para productId
def get_product_id_by_description(tickers, description):
    for ticker in tickers:
        if ticker['description'].lower() == description.lower():
            return ticker['id']
    return None

# Função para mapear productId para description
def get_description_by_product_id(tickers, product_id):
    for ticker in tickers:
        if ticker['id'] == product_id:
            return ticker['description']
    return None

# Função para gerar o gráfico de candlestick com volume
def gerar_candlestick_volume_plotly(df, product_id, tickers):
    description = get_description_by_product_id(tickers, product_id)
    
    # Filtrar dados do produto
    df_produto = df[(df['productId'] == product_id) & 
                     (df['originOperationType'] == 'Match') & 
                     (df['status'] == 'Ativo')][['unitPrice', 'quantity', 'tendency']]
    
    if len(df_produto) < 20:
        return None, f"Dados insuficientes para {description}"
    
    # Resample para dados diários de OHLC
    df_ohlc = df_produto['unitPrice'].resample('D').ohlc()
    df_ohlc.dropna(inplace=True)
    
    # Calcular indicadores técnicos
    df_ohlc['MA10'] = df_ohlc['close'].rolling(window=10).mean()
    df_ohlc['MA20'] = df_ohlc['close'].rolling(window=20).mean()
    df_ohlc['Bollinger_Upper'] = df_ohlc['MA10'] + 2 * df_ohlc['close'].rolling(window=10).std()
    df_ohlc['Bollinger_Lower'] = df_ohlc['MA10'] - 2 * df_ohlc['close'].rolling(window=10).std()
    df_ohlc['Bollinger_Upper_1std'] = df_ohlc['MA10'] + df_ohlc['close'].rolling(window=10).std()
    df_ohlc['Bollinger_Lower_1std'] = df_ohlc['MA10'] - df_ohlc['close'].rolling(window=10).std()
    
    # Resample dos dados de volume para alinhamento
    df_product_resampled = df_produto.resample('D').agg({'quantity': 'sum', 'tendency': 'first'})
    df_volume_total = df_product_resampled['quantity'].reindex(df_ohlc.index, fill_value=0)
    
    # Tentativa de separar volume por compra/venda se disponível
    try:
        df_volume_compra = df_product_resampled[df_product_resampled['tendency'] == 'Compra']['quantity'].reindex(df_ohlc.index, fill_value=0)
        df_volume_venda = df_product_resampled[df_product_resampled['tendency'] == 'Venda']['quantity'].reindex(df_ohlc.index, fill_value=0)
        
        # Criando o DataFrame df_volume com todas as métricas calculadas
        df_volume = pd.DataFrame({
            'Volume_Total': df_volume_total,
            'Volume_Compra': df_volume_compra,
            'Volume_Venda': df_volume_venda,
        }, index=df_ohlc.index)
        df_volume['Saldo_Volume'] = df_volume['Volume_Compra'] - df_volume['Volume_Venda']
        df_volume['Acumulado_Saldo'] = df_volume['Saldo_Volume'].cumsum()
        
        # Adicionando médias móveis para Acumulado_Saldo
        df_volume['MA10_Acumulado_Saldo'] = df_volume['Acumulado_Saldo'].rolling(window=10).mean()
        df_volume['MA20_Acumulado_Saldo'] = df_volume['Acumulado_Saldo'].rolling(window=20).mean()
        
        has_tendency = True
    except Exception as e:
        # Se não conseguir separar por tendência, criar um DataFrame mais simples
        df_volume = pd.DataFrame({
            'Volume_Total': df_volume_total
        }, index=df_ohlc.index)
        has_tendency = False
    
    # Criar figura com subplots
    if has_tendency:
        fig = make_subplots(
            rows=4, cols=1, 
            shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=("Preço", "Volume", "Saldo do Volume", "Acumulado do Saldo"),
            row_heights=[0.5, 0.15, 0.15, 0.2]
        )
    else:
        fig = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True,
            vertical_spacing=0.1,
            subplot_titles=("Preço", "Volume"),
            row_heights=[0.8, 0.2]
        )
    
    # Adicionar candlestick
    fig.add_trace(
        go.Candlestick(
            x=df_ohlc.index,
            open=df_ohlc['open'],
            high=df_ohlc['high'],
            low=df_ohlc['low'],
            close=df_ohlc['close'],
            name='OHLC'
        ),
        row=1, col=1
    )
    
    # Adicionar médias móveis e Bollinger Bands
    fig.add_trace(go.Scatter(x=df_ohlc.index, y=df_ohlc['MA10'], name='MA10', line=dict(color='blue', width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ohlc.index, y=df_ohlc['MA20'], name='MA20', line=dict(color='orange', width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ohlc.index, y=df_ohlc['Bollinger_Upper'], name='Bollinger Upper', line=dict(color='gray', width=1, dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ohlc.index, y=df_ohlc['Bollinger_Lower'], name='Bollinger Lower', line=dict(color='gray', width=1, dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ohlc.index, y=df_ohlc['Bollinger_Upper_1std'], name='Bollinger Upper 1σ', line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_ohlc.index, y=df_ohlc['Bollinger_Lower_1std'], name='Bollinger Lower 1σ', line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
    
    # Adicionar volume
    fig.add_trace(go.Bar(x=df_volume.index, y=df_volume['Volume_Total'], name='Volume', marker_color='gray', opacity=0.7), row=2, col=1)
    
    if has_tendency:
        # Adicionar saldo do volume
        saldo_colors = ['green' if v >= 0 else 'red' for v in df_volume['Saldo_Volume']]
        fig.add_trace(go.Bar(x=df_volume.index, y=df_volume['Saldo_Volume'], name='Saldo do Volume', marker_color=saldo_colors), row=3, col=1)
        
        # Adicionar acumulado do saldo
        acum_colors = ['green' if v >= 0 else 'red' for v in df_volume['Acumulado_Saldo']]
        fig.add_trace(go.Bar(x=df_volume.index, y=df_volume['Acumulado_Saldo'], name='Acumulado do Saldo', marker_color=acum_colors), row=4, col=1)
        fig.add_trace(go.Scatter(x=df_volume.index, y=df_volume['MA20_Acumulado_Saldo'], name='MA20 Acumulado', line=dict(color='gray', width=3)), row=4, col=1)
        fig.add_trace(go.Scatter(x=df_volume.index, y=df_volume['MA10_Acumulado_Saldo'], name='MA10 Acumulado', line=dict(color='gray', width=1)), row=4, col=1)
    
    # Atualizar layout
    fig.update_layout(
        title=f'Análise de Preços e Volume - {description}',
        height=800,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    
    # Informações adicionais
    open_price = df_ohlc.iloc[-1]['open']
    high_price = df_ohlc.iloc[-1]['high']
    low_price = df_ohlc.iloc[-1]['low']
    close_price = df_ohlc.iloc[-1]['close']
    ultimo_ma10 = df_ohlc['MA10'].iloc[-1]
    ultimo_ma20 = df_ohlc['MA20'].iloc[-1]
    
    # Adicionar anotação com informações
    fig.add_annotation(
        x=0.01,
        y=0.98,
        xref="paper",
        yref="paper",
        text=f"Último: {close_price:.2f}<br>Abertura: {open_price:.2f}<br>Máxima: {high_price:.2f}<br>Mínima: {low_price:.2f}<br>MA10: {ultimo_ma10:.2f}<br>MA20: {ultimo_ma20:.2f}",
        showarrow=False,
        font=dict(size=12),
        align="left",
        bgcolor="rgba(255, 255, 255, 0.8)",
        bordercolor="black",
        borderwidth=1,
        borderpad=4
    )
    
    fig.update_xaxes(rangeslider_visible=False)
    
    return fig, None

# Função para gerar o gráfico comparativo de VWAP entre dois produtos usando Plotly
def comparar_vwap_plotly(df, description1, description2, tickers):
    # Obtém os productIds para as descrições fornecidas
    productId1 = get_product_id_by_description(tickers, description1)
    productId2 = get_product_id_by_description(tickers, description2)
    
    # Verifica se os productIds foram encontrados
    if not productId1 or not productId2:
        return None, f"Erro: Não foi possível encontrar os produtos com as descrições '{description1}' ou '{description2}'"
    
    # Filtrar dados pelos dois productId informados
    df1 = df[df['productId'] == productId1][['unitPrice', 'quantity']].rename(columns={'unitPrice': f'unitPrice_{productId1}', 'quantity': f'quantity_{productId1}'})
    df2 = df[df['productId'] == productId2][['unitPrice', 'quantity']].rename(columns={'unitPrice': f'unitPrice_{productId2}', 'quantity': f'quantity_{productId2}'})
    
    # Calcular o VWAP diário para cada produto
    df1['value_price_volume'] = df1[f'unitPrice_{productId1}'] * df1[f'quantity_{productId1}']
    df2['value_price_volume'] = df2[f'unitPrice_{productId2}'] * df2[f'quantity_{productId2}']
    
    # Resumindo os dados diários para calcular VWAP
    df1_vwap = df1.resample('D').sum()
    df1_vwap[f'vwap_{productId1}'] = df1_vwap['value_price_volume'] / df1_vwap[f'quantity_{productId1}']
    
    df2_vwap = df2.resample('D').sum()
    df2_vwap[f'vwap_{productId2}'] = df2_vwap['value_price_volume'] / df2_vwap[f'quantity_{productId2}']
    
    df1_vwap = df1_vwap[df1_vwap[f'quantity_{productId1}'] > 0].dropna(subset=[f'vwap_{productId1}'])
    df2_vwap = df2_vwap[df2_vwap[f'quantity_{productId2}'] > 0].dropna(subset=[f'vwap_{productId2}'])
    
    # Juntando os VWAPs em um único DataFrame
    df_merged = pd.merge(df1_vwap[[f'vwap_{productId1}']], df2_vwap[[f'vwap_{productId2}']], left_index=True, right_index=True, how='inner')
    
    # Verificar se há dados suficientes para análise
    if len(df_merged) < 10:
        return None, "Não há dados suficientes para análise (necessário pelo menos 10 dias de dados)."
    
    # Calculando a diferença de VWAPs entre os produtos
    df_merged['vwap_diff'] = df_merged[f'vwap_{productId1}'] - df_merged[f'vwap_{productId2}']
    
    # Remover outliers usando z-score
    z_scores = (df_merged['vwap_diff'] - df_merged['vwap_diff'].mean()) / df_merged['vwap_diff'].std()
    df_merged_no_outliers = df_merged[(z_scores.abs() < 3)]
    
    # Calculando a média móvel e as bandas de Bollinger da diferença de VWAP
    df_merged_no_outliers['vwap_diff_sma_10'] = df_merged_no_outliers['vwap_diff'].rolling(window=10).mean()
    
    rolling_mean = df_merged_no_outliers['vwap_diff'].rolling(window=10).mean()
    rolling_std = df_merged_no_outliers['vwap_diff'].rolling(window=10).std()
    df_merged_no_outliers['bollinger_upper'] = rolling_mean + (rolling_std * 2)
    df_merged_no_outliers['bollinger_lower'] = rolling_mean - (rolling_std * 2)
    
    # Criando o gráfico com Plotly
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        subplot_titles=(
            f'Comparação VWAP: {description1} vs {description2}',
            'Diferença de VWAPs com Bandas de Bollinger'
        ),
        row_heights=[0.5, 0.5]
    )
    
    # Adicionar linhas de VWAP para cada produto
    fig.add_trace(
        go.Scatter(
            x=df_merged.index,
            y=df_merged[f'vwap_{productId1}'],
            name=description1,
            mode='lines',
            line=dict(color='blue')
        ),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=df_merged.index,
            y=df_merged[f'vwap_{productId2}'],
            name=description2,
            mode='lines',
            line=dict(color='green')
        ),
        row=1, col=1
    )
    
    # Adicionar diferença de VWAPs e bandas de Bollinger
    fig.add_trace(
        go.Scatter(
            x=df_merged_no_outliers.index,
            y=df_merged_no_outliers['vwap_diff'],
            name='Diferença de VWAPs',
            mode='lines',
            line=dict(color='purple')
        ),
        row=2, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=df_merged_no_outliers.index,
            y=df_merged_no_outliers['vwap_diff_sma_10'],
            name='Média Móvel 10 Períodos',
            mode='lines',
            line=dict(color='orange')
        ),
        row=2, col=1
    )
    
    # Adicionar área entre as bandas de Bollinger
    fig.add_trace(
        go.Scatter(
            x=df_merged_no_outliers.index,
            y=df_merged_no_outliers['bollinger_upper'],
            name='Banda Superior',
            mode='lines',
            line=dict(width=0),
            showlegend=False
        ),
        row=2, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=df_merged_no_outliers.index,
            y=df_merged_no_outliers['bollinger_lower'],
            name='Banda Inferior',
            mode='lines',
            line=dict(width=0),
            fill='tonexty',
            fillcolor='rgba(128, 128, 128, 0.3)',
            showlegend=False
        ),
        row=2, col=1
    )
    
    # Adicionar linhas das bandas de Bollinger
    fig.add_trace(
        go.Scatter(
            x=df_merged_no_outliers.index,
            y=df_merged_no_outliers['bollinger_upper'],
            name='Bandas de Bollinger',
            mode='lines',
            line=dict(color='gray', dash='dash')
        ),
        row=2, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=df_merged_no_outliers.index,
            y=df_merged_no_outliers['bollinger_lower'],
            name='',
            mode='lines',
            line=dict(color='gray', dash='dash'),
            showlegend=False
        ),
        row=2, col=1
    )
    
    # Atualizar layout
    fig.update_layout(
        height=800,
        title_text=f'Análise Comparativa: {description1} vs {description2}',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        hovermode="x unified"
    )
    
    fig.update_yaxes(title_text="VWAP", row=1, col=1)
    fig.update_yaxes(title_text="Diferença", row=2, col=1)
    
    return fig, None

# Função para gerar resumo OHLC
# Função para gerar resumo OHLC
def gerar_resumo_ohlc(df, tickers):
    """
    Gera um DataFrame com o resumo de OHLC para o último dia de negociação,
    sem incluir o cálculo de tendência.
    """
    ultimo_dia = df.index.max().date()
    df_ultimo_dia = df[df.index.date == ultimo_dia]
    
    resumo_ohlc = df_ultimo_dia[df_ultimo_dia['originOperationType'] == 'Match'].groupby('productId')['unitPrice'].agg(['first', 'max', 'min', 'last'])
    resumo_ohlc = resumo_ohlc.rename(columns={'first': 'open', 'max': 'high', 'min': 'low', 'last': 'close'})
    
    # Adicionar a descrição do produto
    resumo_ohlc['description'] = resumo_ohlc.index.map(lambda product_id: 
                                                        get_description_by_product_id(tickers, product_id))
    
    # Calcular variação diária
    dia_anterior = ultimo_dia - pd.Timedelta(days=1)
    df_dia_anterior = df[df.index.date == dia_anterior]
    
    # Se não houver dados do dia anterior, tente encontrar o dia de negociação mais recente
    if df_dia_anterior.empty:
        dias_anteriores = sorted(list(set(df[df.index.date < ultimo_dia].index.date)), reverse=True)
        if dias_anteriores:
            dia_anterior = dias_anteriores[0]
            df_dia_anterior = df[df.index.date == dia_anterior]
    
    resumo_dia_anterior = df_dia_anterior[df_dia_anterior['originOperationType'] == 'Match'].groupby('productId')['unitPrice'].agg(['last'])
    resumo_dia_anterior = resumo_dia_anterior.rename(columns={'last': 'close_anterior'})
    
    # Mesclar os dados
    resumo_ohlc = pd.merge(resumo_ohlc, resumo_dia_anterior, left_index=True, right_index=True, how='left')
    
    # Calcular variação
    resumo_ohlc['variacao'] = (resumo_ohlc['close'] - resumo_ohlc['close_anterior']) / resumo_ohlc['close_anterior']
    
    # Note que todo o cálculo de média móvel e tendência foi removido
    
    return resumo_ohlc, ultimo_dia

# Função para criar uma tabela interativa com Plotly
# Função para criar uma tabela interativa com Plotly
def criar_tabela_interativa(resumo_ohlc, ultimo_dia):
    if resumo_ohlc.empty:
        return None, "Não há dados para exibir."
    
    # Preparar os dados para a tabela
    df_table = resumo_ohlc[['description', 'open', 'high', 'low', 'close', 'variacao']].copy()
    df_table.reset_index(inplace=True)
    df_table.rename(columns={'index': 'productId'}, inplace=True)
    
    # Formatar os valores numéricos
    df_table['open'] = df_table['open'].round(2)
    df_table['high'] = df_table['high'].round(2)
    df_table['low'] = df_table['low'].round(2)
    df_table['close'] = df_table['close'].round(2)
    
    # Formatar a variação como percentual
    df_table['variacao'] = df_table['variacao'].apply(lambda x: f"{x*100:.2f}%" if pd.notna(x) else "N/A")
    
    # Criar tabela com Plotly
    fig = go.Figure(data=[go.Table(
        header=dict(
            values=['Produto', 'Abertura', 'Máxima', 'Mínima', 'Fechamento', 'Variação'],
            fill_color='lightgray',
            align='center',
            font=dict(size=12)
        ),
        cells=dict(
            values=[
                df_table['description'],
                df_table['open'],
                df_table['high'],
                df_table['low'],
                df_table['close'],
                df_table['variacao']
            ],
            align='center',
            font_size=11,
            height=30,
            fill_color=[
                'white',
                'white',
                'white',
                'white',
                'white',
                ['green' if '-' not in val else 'red' for val in df_table['variacao']]
            ],
            font_color=[
                'black',
                'black',
                'black',
                'black',
                'black',
                'white'
            ]
        )
    )])
    
    # Melhorar layout
    fig.update_layout(
        title=f"Resumo do dia {ultimo_dia.strftime('%d/%m/%Y')}",
        height=400 + len(df_table) * 30,  # ajustar altura com base no número de linhas
        margin=dict(l=10, r=10, t=50, b=10)
    )
    
    return fig, None

# Interface do usuário com Streamlit
def main():
    # Verificar login antes de mostrar o conteúdo principal
    if not check_password():
        return
    
    st.title(TITLE)
    st.caption(f"Desenvolvido por {AUTHOR}")
    
    st.sidebar.title("Configurações")
    
    # Adicionar configurações de login na sidebar
    with st.sidebar.expander("Configurações de API"):
        apiKey = st.text_input("API Key", value="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjb21wYW55SWQiOiI3MWJMTWFCWWxqNjlLMG0yODRlR0p3dmRORXp5QU9nUCIsInRpbWVzdGFtcCI6MTY1OTM4ODc1MzcwNiwiaWF0IjoxNjU5Mzg4NzUzfQ.Ld5_SOaSUF1GMlRyaOndRqT_OtXCvS6UjDUeKNByo5w", type="password")
        cod = st.number_input("Código da Empresa", value=1447)
        email = st.text_input("Email", value="tnavarro@bemenergia.com")
        password = st.text_input("Senha", value="T@rik0b0", type="password")
    
    # Adicionar configurações de data na sidebar
    with st.sidebar.expander("Período de Análise", expanded=True):
        today = datetime.now().date()
        data_inicio = st.date_input("Data Inicial", value=today - timedelta(days=180))
        data_fim = st.date_input("Data Final", value=today)
    
    # Converter datas para string no formato esperado pela API
    data_inicio_str = data_inicio.strftime("%Y-%m-%d")
    data_fim_str = data_fim.strftime("%Y-%m-%d")
    
    # Botão para carregar dados
    if st.sidebar.button("Carregar Dados"):
        with st.spinner("Fazendo login na API..."):
            try:
                # Login na API
                loginehub = loginAPInew(cod, email, password, apiKey)
                token = loginehub[1]
                refreshToken = loginehub[2]  # Assumindo que refreshToken está nesta posição
                
                st.sidebar.success("Login realizado com sucesso!")
                
                # Obter wallet_id e tickers
                with st.spinner("Obtendo tickers..."):
                    wallet_id = wallet(token, apiKey)
                    tickers = negotiabletickers(token, apiKey, wallet_id)
                
                # Carregar base de dados
                with st.spinner(f"Carregando dados de {data_inicio_str} a {data_fim_str}..."):
                    df = carregar_base_dados(token, apiKey, data_inicio_str, data_fim_str, refreshToken)
                
                # Armazenar os dados na sessão para uso em todo o aplicativo
                st.session_state.df = df
                st.session_state.tickers = tickers
                st.session_state.loaded = True
                
                st.sidebar.success(f"Dados carregados com sucesso! Total de registros: {len(df)}")
            
            except Exception as e:
                st.sidebar.error(f"Erro ao carregar dados: {str(e)}")
                st.session_state.loaded = False
    
    # Verificar se os dados foram carregados
    if not hasattr(st.session_state, 'loaded') or not st.session_state.loaded:
        st.warning("Por favor, configure os parâmetros e clique em 'Carregar Dados' para iniciar.")
        return
    
    # Navegar entre as diferentes visualizações
    st.sidebar.title("Navegação")
    page = st.sidebar.radio(
        "Escolha uma visualização:",
        ["Resumo do Dia", "Análise de Preços", "Comparação de Produtos"]
    )
    
    # Obter os dados da sessão
    df = st.session_state.df
    tickers = st.session_state.tickers
    
    # Exibir a visualização selecionada
    if page == "Resumo do Dia":
        st.header("Resumo do Dia")
        
        resumo_ohlc, ultimo_dia = gerar_resumo_ohlc(df, tickers)
        
        if resumo_ohlc.empty:
            st.warning("Não há dados para o período selecionado.")
        else:
            # Exibir tabela interativa
            fig, error = criar_tabela_interativa(resumo_ohlc, ultimo_dia)
            if error:
                st.error(error)
            else:
                st.plotly_chart(fig, use_container_width=True)
    
    elif page == "Análise de Preços":
        st.header("Análise de Preços")
        
        # Lista de produtos disponíveis
        product_descriptions = [ticker['description'] for ticker in tickers 
                              if ticker['description'] not in blacklist_produtos]
        product_descriptions.sort()
        
        # Seleção de produto
        selected_description = st.selectbox("Selecione um produto:", product_descriptions)
        
        if selected_description:
            selected_product_id = get_product_id_by_description(tickers, selected_description)
            
            with st.spinner(f"Gerando análise de preços para {selected_description}..."):
                fig, error = gerar_candlestick_volume_plotly(df, selected_product_id, tickers)
                
                if error:
                    st.error(error)
                elif fig:
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Não foi possível gerar o gráfico.")
    
    elif page == "Comparação de Produtos":
        st.header("Comparação entre Produtos")
        
        # Lista de produtos disponíveis
        product_descriptions = [ticker['description'] for ticker in tickers 
                              if ticker['description'] not in blacklist_produtos]
        product_descriptions.sort()
        
        # Seleção de produtos para comparação
        col1, col2 = st.columns(2)
        with col1:
            product1 = st.selectbox("Produto 1:", product_descriptions, index=0)
        with col2:
            # Inicializar com um índice diferente de 0, se possível
            default_index = min(1, len(product_descriptions) - 1)
            product2 = st.selectbox("Produto 2:", product_descriptions, index=default_index)
        
        if st.button("Comparar Produtos"):
            with st.spinner(f"Gerando comparação entre {product1} e {product2}..."):
                fig, error = comparar_vwap_plotly(df, product1, product2, tickers)
                
                if error:
                    st.error(error)
                elif fig:
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Não foi possível gerar a comparação.")

if __name__ == "__main__":
    main()