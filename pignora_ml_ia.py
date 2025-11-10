import os
import re
import time
import requests
import numpy as np
import pandas as pd
import feedparser
from bs4 import BeautifulSoup
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
import altair as alt

# ================== CONFIGURACIÓN INICIAL ==================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Pignora - Estimador de Empeño", page_icon="💰", layout="wide")
st.title("💰 Pignora - Estimador Multiactivo")

st.markdown("""
¡Bienvenido a **Pignora**!  
Selecciona el tipo de activo o servicio para calcular su valor o simular una operación financiera:

- **💻 Electrónica:** busca precios en eBay, Google Shopping y Encuentra24.  
- **🟡 Prendas de Oro:** calcula por peso y pureza.  
- **🌐 Activos Digitales:** estima valor de dominios o webs.  
- **💳 Custodia / Vende tu saldo PayPal:** simula operaciones Fintech seguras.  
""")

# ================== FUNCIONES DE UTILIDAD ==================
TASAS_CAMBIO_A_USD = {"USD": 1.0, "EUR": 1.07, "GBP": 1.22}

def convertir_a_usd(precio: float, moneda_origen: str) -> float:
    return precio * TASAS_CAMBIO_A_USD.get(moneda_origen.upper(), 1)

def construir_query(categoria: str, modelo: str) -> str:
    modelo, categoria = (modelo or "").strip(), (categoria or "").strip()
    if not modelo and not categoria: return ""
    if not modelo: return categoria
    if not categoria or categoria.lower() in modelo.lower(): return modelo
    return f"{modelo} {categoria}".strip()

# ================== ESTIMADOR DE ORO ==================
def estimar_oro(peso_gramos: float, pureza: int):
    precio_oro_puro = 75.0
    factor_pureza = pureza / 24
    valor_bruto = peso_gramos * precio_oro_puro * factor_pureza
    valor_empeno = valor_bruto * 0.85
    return round(valor_bruto, 2), round(valor_empeno, 2)

# ================== ESTIMADOR DE ACTIVOS DIGITALES ==================
def estimar_activo_digital(url: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    site = url.replace("https://", "").replace("http://", "").split("/")[0]
    check_url = f"https://www.siteprice.org/website-worth/{site}"
    st.markdown(f"🔹 **Valorando dominio:** [{check_url}]({check_url})")

    try:
        resp = requests.get(check_url, headers=headers, timeout=10)
        resp.raise_for_status()
        match = re.search(r"\$[0-9,]+", resp.text)
        if match:
            val = float(match.group(0).replace("$", "").replace(",", ""))
            valor_empeno = val * 0.5
            return val, valor_empeno
        else:
            st.info("ℹ️ No se detectó valoración disponible para ese dominio.")
            return None, None
    except Exception as e:
        st.warning(f"⚠️ Error estimando activo digital: {e}")
        return None, None

# ================== FUNCIONES FINTECH ==================
def simular_escrow(monto: float, dias: int, comision_pct: float = 3.5):
    comision = monto * comision_pct / 100
    neto = monto - comision
    return {
        "monto_inicial": round(monto, 2),
        "comision": round(comision, 2),
        "monto_liberado": round(neto, 2),
        "dias": dias
    }

def simular_paypal_to_ach(monto: float, comision_pct: float = 8.0):
    comision = monto * comision_pct / 100
    neto = monto - comision
    return {
        "deposito_paypal": round(monto, 2),
        "comision": round(comision, 2),
        "transferencia_ach": round(neto, 2),
        "tiempo": "24 horas"
    }

# ================== SCRAPING / ELECTRÓNICA ==================
def buscar_ebay_publico(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.ebay.com/sch/i.html?_nkw={slug}&_sop=12"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200: return [], []
        matches = re.findall(r'\$\s?\d+(?:\.\d{2})?', resp.text)
        for m in matches:
            val = float(m.replace("$", "").replace(",", ""))
            if 20 < val < 10000: precios.append(val)
        for p in precios[:10]:
            resultados.append({"Fuente": "eBay", "Título": query, "Precio USD": p, "Link": url})
        return precios, resultados
    except Exception:
        return [], []

# ================== CÁLCULO BASE ==================
def calcular_valor_empeno(precios_usd, antiguedad, condicion):
    if not precios_usd: return None
    arr = np.array(precios_usd)
    mediana, promedio, minimo, maximo = np.median(arr), np.mean(arr), np.min(arr), np.max(arr)
    f_ant = max(0.30, 1 - 0.10 * antiguedad)
    f_cond = round(min(1.0, 0.4 + 0.6 * (condicion - 1) / 9), 2)
    f_riesgo = 0.55
    valor = mediana * f_ant * f_cond * f_riesgo
    return dict(mediana=mediana, promedio=promedio, minimo=minimo, maximo=maximo,
                valor_base=valor, factor_antiguedad=f_ant, factor_condicion=f_cond, factor_riesgo=f_riesgo)

# ================== INTERFAZ PRINCIPAL ==================
tipo_activo = st.radio("Selecciona una opción:",
                       ["💻 Electrónica", "🟡 Prendas de Oro", "🌐 Activos Digitales", "💳 Custodia / Vende tu saldo PayPal"],
                       horizontal=True)

# --- SIDEBARS ---
if tipo_activo == "💻 Electrónica":
    with st.sidebar:
        categoria = st.selectbox("Tipo de artículo", ["Laptop", "iPhone", "Smartphone Android", "Consola de videojuegos", "Televisor", "Otro"])
        modelo = st.text_input("Modelo / Referencia", "PlayStation 4")
        antiguedad = st.slider("Antigüedad (años)", 0, 10, 4)
        condicion = st.slider("Condición (1 = mala, 10 = excelente)", 1, 10, 7)
elif tipo_activo == "🟡 Prendas de Oro":
    with st.sidebar:
        peso_gramos = st.number_input("Peso (gramos)", 0.1, 500.0, 10.0, 0.1)
        pureza = st.selectbox("Pureza (quilates)", [10, 14, 18, 22, 24], index=2)
elif tipo_activo == "🌐 Activos Digitales":
    with st.sidebar:
        url = st.text_input("URL del dominio / red social", "https://tusitio.com")
elif tipo_activo == "💳 Custodia / Vende tu saldo PayPal":
    with st.sidebar:
        st.header("⚙️ Simulador Fintech")
        monto = st.number_input("Monto (USD)", min_value=10.0, value=100.0, step=10.0)
        dias = st.slider("Días de retención (Escrow)", 1, 30, 7)

# ================== BOTÓN PRINCIPAL ==================
if st.button("🚀 Ejecutar Operación / Calcular", use_container_width=True):

    # --- ORO ---
    if tipo_activo == "🟡 Prendas de Oro":
        bruto, empeno = estimar_oro(peso_gramos, pureza)
        st.subheader("🟡 Estimación de Prenda de Oro")
        st.metric("💰 Valor comercial", f"${bruto:,.2f}")
        st.metric("💵 Valor de empeño sugerido", f"${empeno:,.2f}")

    # --- DIGITAL ---
    elif tipo_activo == "🌐 Activos Digitales":
        bruto, empeno = estimar_activo_digital(url)
        if bruto:
            st.metric("💻 Valor estimado del sitio", f"${bruto:,.2f}")
            st.metric("💵 Valor de empeño sugerido", f"${empeno:,.2f}")

    # --- CUSTODIA / PAYPAL ---
    elif tipo_activo == "💳 Custodia / Vende tu saldo PayPal":
        st.subheader("💼 Simulador de Custodia (Escrow)")
        escrow = simular_escrow(monto, dias)
        st.success(f"""
        💰 Monto en custodia: ${escrow['monto_inicial']:.2f}  
        💸 Comisión (3.5%): ${escrow['comision']:.2f}  
        🏦 Monto liberado: ${escrow['monto_liberado']:.2f}  
        ⏳ Retención: {escrow['dias']} días
        """)
        df1 = pd.DataFrame({"Concepto": ["Comisión", "Monto liberado"], "Valor": [escrow["comision"], escrow["monto_liberado"]]})
        st.altair_chart(alt.Chart(df1).mark_arc(innerRadius=50).encode(theta="Valor", color="Concepto"), use_container_width=True)

        st.markdown("---")
        st.subheader("💳 Simular venta de saldo PayPal → ACH")
        paypal = simular_paypal_to_ach(monto)
        st.success(f"""
        📥 Depósito PayPal: ${paypal['deposito_paypal']:.2f}  
        💸 Comisión (8%): ${paypal['comision']:.2f}  
        🏦 Transferencia ACH neta: ${paypal['transferencia_ach']:.2f}  
        ⏱️ Tiempo estimado: {paypal['tiempo']}
        """)
        df2 = pd.DataFrame({"Concepto": ["Comisión", "Transferencia neta"], "Valor": [paypal["comision"], paypal["transferencia_ach"]]})
        st.altair_chart(alt.Chart(df2).mark_arc(innerRadius=50).encode(theta="Valor", color="Concepto"), use_container_width=True)
