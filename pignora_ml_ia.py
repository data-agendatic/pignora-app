import os, re, requests, numpy as np, pandas as pd, feedparser, streamlit as st, altair as alt
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

# ================== CONFIGURACIÓN INICIAL ==================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Pignora - Estimador Multiactivo", page_icon="💰", layout="wide")
st.title("💰 Pignora - Estimador Multiactivo")

st.markdown("""
¡Bienvenido a **Pignora**!  
Evalúa diferentes tipos de activos y servicios financieros:

- **💻 Electrónica:** precios de mercado en tiempo real.  
- **🟡 Oro:** cálculo por peso y pureza.  
- **🌐 Activos Digitales:** estima valor de webs o redes.  
- **🔒 Escrow:** simula custodia temporal con tarifa.  
- **💵 PayPal:** vende tu saldo y recibe ACH local.  
---
""")

# ================== FUNCIONES AUXILIARES ==================
def estimar_oro(peso_gramos: float, pureza: int):
    precio_oro_puro = 75.0  # USD/gramo
    valor_bruto = peso_gramos * precio_oro_puro * (pureza / 24)
    valor_empeno = valor_bruto * 0.85
    return round(valor_bruto, 2), round(valor_empeno, 2)

def estimar_activo_digital(url: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    site = url.replace("https://", "").replace("http://", "").split("/")[0]
    check_url = f"https://www.siteprice.org/website-worth/{site}"
    st.markdown(f"🔗 **Fuente:** [siteprice.org]({check_url})")
    try:
        resp = requests.get(check_url, headers=headers, timeout=10)
        resp.raise_for_status()
        match = re.search(r"\$[0-9,]+", resp.text)
        if match:
            val = float(match.group(0).replace("$", "").replace(",", ""))
            return val, val * 0.5
        else:
            st.info("ℹ️ No se detectó valoración para ese dominio.")
            return None, None
    except Exception as e:
        st.warning(f"⚠️ Error estimando activo digital: {e}")
        return None, None

def buscar_ebay(query):
    url = f"https://www.ebay.com/sch/i.html?_nkw={query.replace(' ', '+')}"
    try:
        html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}).text
        precios = [float(p.replace('$', '')) for p in re.findall(r'\$\d+(?:\.\d{2})?', html) if 20 < float(p.replace('$', '')) < 10000]
        return precios
    except:
        return []

def calcular_valor_empeno(precios_usd, antiguedad, condicion):
    if not precios_usd: return None
    arr = np.array(precios_usd)
    mediana, promedio = np.median(arr), np.mean(arr)
    f_ant = max(0.3, 1 - 0.1 * antiguedad)
    f_cond = round(min(1.0, 0.4 + 0.6 * (condicion - 1) / 9), 2)
    valor = mediana * f_ant * f_cond * 0.55
    return dict(mediana=mediana, promedio=promedio, valor=valor)

# ================== ESTILO DE BOTONES ==================
st.markdown("""
<style>
div.stButton > button:first-child {
    background-color: #e63946;
    color: white;
    font-weight: bold;
    border: none;
    border-radius: 8px;
    height: 3em;
    width: 100%;
    box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    transition: all 0.3s ease;
}
div.stButton > button:first-child:hover {
    background-color: #ff4b5c;
    transform: scale(1.02);
}
.metric-small {font-size: 0.9em; color: gray;}
</style>
""", unsafe_allow_html=True)

# ================== INTERFAZ PRINCIPAL ==================
col1, col2 = st.columns(2)

# ---------- PANEL ELECTRÓNICA ----------
with col1:
    st.subheader("💻 Electrónica")
    categoria = st.selectbox("Tipo", ["Laptop","iPhone","Consola","Televisor","Otro"], key="cat")
    modelo = st.text_input("Modelo / Referencia", "PlayStation 4", key="mod")
    antiguedad = st.slider("Antigüedad (años)", 0, 10, 3, key="ant")
    condicion = st.slider("Condición (1-10)", 1, 10, 7, key="cond")

    if st.button("🚀 Estimar Electrónica"):
        precios = buscar_ebay(f"{categoria} {modelo}")
        if precios:
            datos = calcular_valor_empeno(precios, antiguedad, condicion)
            st.metric("💰 Mediana", f"${datos['mediana']:.2f}")
            st.metric("💵 Valor estimado de empeño", f"${datos['valor']:.2f}")
            st.caption("Fuente: eBay (referencias recientes).")
        else:
            st.error("No se hallaron precios para esa búsqueda.")

# ---------- PANEL ORO ----------
with col1:
    st.subheader("🟡 Prendas de Oro")
    peso = st.number_input("Peso (g)", 0.1, 500.0, 10.0, 0.1, key="peso")
    pureza = st.selectbox("Pureza (K)", [10, 14, 18, 22, 24], index=2, key="pureza")

    if st.button("🔍 Calcular Oro"):
        bruto, empeño = estimar_oro(peso, pureza)
        st.metric("💰 Valor comercial", f"${bruto:,.2f}")
        st.metric("💵 Valor empeño sugerido", f"${empeño:,.2f}")
        st.caption("Basado en $75/g de oro 24K y 85% valor empeño.")

# ---------- PANEL DIGITAL ----------
with col2:
    st.subheader("🌐 Activos Digitales")
    url = st.text_input("Dominio / Red Social / Web", "https://tusitio.com", key="url")

    if st.button("🌎 Estimar Activo Digital"):
        bruto, empeño = estimar_activo_digital(url)
        if bruto:
            st.metric("💻 Valor estimado del dominio", f"${bruto:,.2f}")
            st.metric("💵 Valor empeño sugerido", f"${empeño:,.2f}")
            st.caption("Estimación web basada en tráfico y SEO público.")
        else:
            st.error("No se pudo estimar ese dominio.")

# ---------- PANEL ESCROW ----------
with col2:
    st.subheader("🔒 Escrow - Custodia Temporal")
    monto = st.number_input("Monto a custodiar (USD)", 10.0, 10000.0, 500.0, 10.0, key="escrow")
    dias = st.slider("Duración del acuerdo (días)", 1, 90, 15, key="dias")

    if st.button("🧾 Simular Escrow"):
        tarifa = 0.015 * monto
        st.metric("💵 Comisión de custodia", f"${tarifa:,.2f}")
        st.metric("📅 Duración", f"{dias} días")
        st.caption("Pignora actúa como tercero neutral. Comisión: 1.5%.")
        pie = pd.DataFrame({
            'Concepto': ['Monto Liberado', 'Comisión Escrow'],
            'Valor': [monto - tarifa, tarifa]
        })
        chart = alt.Chart(pie).mark_arc().encode(
            theta='Valor', color='Concepto', tooltip=['Concepto','Valor']
        )
        st.altair_chart(chart, use_container_width=True)

# ---------- PANEL PAYPAL ----------
st.markdown("---")
st.subheader("💵 Vende tu Saldo PayPal")
monto_pp = st.number_input("Monto en PayPal (USD)", 10.0, 2000.0, 100.0, 10.0, key="pp")

if st.button("💸 Simular Venta PayPal"):
    comision = monto_pp * 0.07
    recibido = monto_pp - comision
    st.metric("💵 Recibirás vía ACH", f"${recibido:,.2f}")
    st.metric("📉 Comisión aplicada", f"${comision:,.2f}")
    st.caption("Depósito local en 24h. Comisión del 7%.")
    pie2 = pd.DataFrame({
        'Concepto': ['Monto a recibir', 'Comisión Pignora'],
        'Valor': [recibido, comision]
    })
    chart2 = alt.Chart(pie2).mark_arc().encode(
        theta='Valor', color='Concepto', tooltip=['Concepto','Valor']
    )
    st.altair_chart(chart2, use_container_width=True)
