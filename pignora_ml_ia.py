import os
import requests
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
import pandas as pd
import altair as alt
import re
import time

# ================== CONFIGURACIÓN INICIAL ==================
load_dotenv()

# --- CLAVES API ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inicializar cliente de OpenAI solo si la API Key está presente
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Pignora - Estimador de Empeño", page_icon="💰", layout="wide")
st.title("💰 Pignora - Estimador de Valor de Empeño")

st.markdown("""
¡Bienvenido a Pignora! Esta herramienta te ayuda a estimar un valor de empeño combinando:

1.  **🏷️ Precios de Mercado:** Busca activamente precios de artículos similares en **eBay**.
2.  **📉 Modelo de Depreciación:** Aplica ajustes por antigüedad y condición del artículo.
3.  **🤖 Ajuste Opcional con IA:** Ofrece una evaluación premium para una recomendación más precisa (simulado como $0.99 por evaluación).
""")

# ================== FUNCIONES DE UTILIDAD ==================

TASAS_CAMBIO_A_USD = {
    "USD": 1.0,
    "EUR": 1.07,
    "GBP": 1.22,
}

def convertir_a_usd(precio: float, moneda_origen: str) -> float:
    moneda_origen = moneda_origen.upper()
    tasa = TASAS_CAMBIO_A_USD.get(moneda_origen)
    if tasa:
        return precio * tasa
    return precio

def construir_query(categoria: str, modelo: str) -> str:
    base = categoria if categoria != "Otro" else ""
    texto = (base + " " + modelo).strip()
    return texto if texto else modelo


# ================== FUNCIÓN PRINCIPAL: BÚSQUEDA EN eBAY ==================
def buscar_ebay_api(query: str):
    """
    Busca precios en eBay usando la API pública (Browse API).
    Devuelve precios ya convertidos a USD.
    """
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {
        "X-EBAY-C-ENDUSERCTX": "contextualLocation=country=US,zip=90210",
        "Accept": "application/json",
        "User-Agent": "Pignora-Demo/1.0",
    }

    params = {
        "q": query,
        "limit": 20,
        "filter": "priceCurrency:USD,conditionIds:{3000|4000|5000}",
    }

    precios_usd = []
    resultados_crudos = []

    st.subheader("🔍 Diagnóstico API eBay:")
    st.write(f"Buscando con query: `{query}`")

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        st.write(f"Status API eBay: {resp.status_code}")
        resp.raise_for_status()

        data = resp.json()
        items = data.get("itemSummaries", [])

        if not items:
            st.info("No se encontraron resultados en eBay.")
            return [], [], "eBay"

        for item in items:
            price_data = item.get("price", {})
            if "value" in price_data:
                precio = float(price_data["value"])
                precios_usd.append(precio)
                resultados_crudos.append({
                    "Título": item.get("title", "")[:60] + "...",
                    "Precio USD": f"{precio:,.2f}",
                    "Link": item.get("itemWebUrl", ""),
                    "Condición": item.get("condition", "Desconocido"),
                })

        return precios_usd, resultados_crudos, "eBay"

    except Exception as e:
        st.error(f"Error al consultar eBay API: {e}")
        return [], [], "eBay"


# ================== CÁLCULOS ==================
def calcular_valor_empeno(precios_usd: list, antiguedad: int, condicion: int):
    if not precios_usd:
        return None

    precios_np = np.array(precios_usd)
    mediana = float(np.median(precios_np))
    promedio = float(np.mean(precios_np))
    minimo = float(np.min(precios_np))
    maximo = float(np.max(precios_np))

    factor_antiguedad = max(0.30, 1 - 0.10 * antiguedad)
    factor_condicion = 0.4 + (0.6 * (condicion - 1) / 9)
    factor_condicion = round(min(1.0, factor_condicion), 2)
    factor_riesgo_ganancia = 0.55

    valor_base = mediana * factor_antiguedad * factor_condicion * factor_riesgo_ganancia

    return {
        "mediana": mediana,
        "promedio": promedio,
        "minimo": minimo,
        "maximo": maximo,
        "valor_base": valor_base,
        "factor_antiguedad": factor_antiguedad,
        "factor_condicion": factor_condicion,
        "factor_riesgo_ganancia": factor_riesgo_ganancia,
    }


def generar_comentario_ia(query: str, descripcion: str, precio_original: float, antiguedad: int, condicion: int, stats: dict):
    if not client:
        return "⚠️ IA no disponible: No se encontró la API key de OpenAI."

    prompt = f"""
Eres un tasador experto de casas de empeño en Latinoamérica, conocido por tus recomendaciones realistas y equilibradas.

Artículo: "{query}"
Descripción: "{descripcion}"
Precio original (nuevo): {precio_original:.2f} USD
Antigüedad: {antiguedad} años
Condición: {condicion}/10

Datos de mercado (USD):
Mediana: {stats['mediana']:.2f}, Promedio: {stats['promedio']:.2f},
Rango: {stats['minimo']:.2f}-{stats['maximo']:.2f}
Valor base estimado: {stats['valor_base']:.2f} USD

Tu respuesta en formato exacto:
VALOR_RECOMENDADO_FINAL: <número en USD> - <justificación breve>.
"""

    try:
        with st.spinner("La IA está evaluando el artículo..."):
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un tasador experto de empeños."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
                max_tokens=100,
            )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Error consultando la IA: {e}"


# ================== INTERFAZ DE USUARIO ==================
with st.sidebar:
    st.header("⚙️ Configuración del Artículo")
    categoria = st.selectbox(
        "Tipo de artículo",
        ["Laptop", "iPhone", "Smartphone Android", "Consola de videojuegos",
         "Televisor", "Herramienta eléctrica", "Joya / Reloj", "Otro"],
    )
    modelo = st.text_input("Modelo / Referencia", "PlayStation 4")
    descripcion = st.text_area("Descripción", "Buen estado general, uso moderado, incluye accesorios.")
    precio_original = st.number_input("Precio original (USD)", min_value=10.0, value=500.0, step=10.0)
    antiguedad = st.slider("Antigüedad (años)", 0, 10, 4)
    condicion = st.slider("Condición (1 = mala, 10 = excelente)", 1, 10, 7)
    usar_ia_premium = st.checkbox("Activar IA premium ($0.99)", value=False)

st.markdown("---")
if st.button("🚀 Calcular Estimación de Empeño", type="primary", use_container_width=True):
    if not modelo and categoria == "Otro":
        st.error("❌ Especifica al menos un modelo o categoría.")
        st.stop()

    query = construir_query(categoria, modelo)
    st.subheader(f"🔍 Evaluando: '{query}'")

    precios_api_usd, resultados_crudos_api, site_usado = buscar_ebay_api(query)

    precios_totales_usd = precios_api_usd
    if not precios_totales_usd:
        st.error("❌ No se pudo obtener ningún precio de referencia en eBay.")
        st.stop()

    st.success(f"✔️ Se encontraron {len(precios_api_usd)} resultados en eBay.")
    if resultados_crudos_api:
        df_api = pd.DataFrame(resultados_crudos_api)
        st.dataframe(df_api, use_container_width=True, hide_index=True,
                     column_config={"Link": st.column_config.LinkColumn("Link", display_text="Ver →")})

    st.markdown("---")
    st.subheader("3️⃣ Análisis de Mercado y Cálculo Base")

    stats = calcular_valor_empeno(precios_totales_usd, antiguedad, condicion)
    if stats is None:
        st.error("❌ No se pudo calcular el valor de empeño.")
        st.stop()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Mediana (USD)", f"${stats['mediana']:,.2f}")
    col2.metric("📊 Promedio (USD)", f"${stats['promedio']:,.2f}")
    col3.metric("⬇️ Mínimo", f"${stats['minimo']:,.2f}")
    col4.metric("⬆️ Máximo", f"${stats['maximo']:,.2f}")

    st.markdown("#### Factores de Ajuste")
    st.info(f"Antigüedad: {stats['factor_antiguedad']:.2f} | Condición: {stats['factor_condicion']:.2f} | Margen Empeño: {stats['factor_riesgo_ganancia']:.2f}")

    st.subheader(f"✅ Valor Base Sugerido: **${stats['valor_base']:,.2f} USD**")

    st.markdown("#### Distribución de Precios")
    df_precios = pd.DataFrame({'Precio (USD)': precios_totales_usd})
    chart = alt.Chart(df_precios).mark_bar().encode(
        alt.X('Precio (USD)', bin=alt.Bin(maxbins=20)),
        alt.Y('count()', title='Frecuencia'),
        tooltip=['Precio (USD)', 'count()']
    ).properties(title='Histograma de Precios en eBay')
    st.altair_chart(chart, use_container_width=True)

    if usar_ia_premium:
        comentario_ia = generar_comentario_ia(query, descripcion, precio_original, antiguedad, condicion, stats)
        if "VALOR_RECOMENDADO_FINAL:" in comentario_ia:
            parts = comentario_ia.split("VALOR_RECOMENDADO_FINAL:")
            valor_str = parts[1].split('-')[0].strip().replace("$", "").replace(",", "")
            valor_str_clean = re.sub(r'[^\d.]+', '', valor_str)
            valor_ia = float(valor_str_clean)
            justificacion = parts[1].split('-', 1)[1].strip()
            st.success(f"**IA Premium:** ${valor_ia:,.2f} USD — *{justificacion}*")
        else:
            st.warning(comentario_ia)

    st.caption("⚠️ Esta herramienta es una demo. Los precios y factores son estimativos para fines ilustrativos.")
