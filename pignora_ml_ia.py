import os
import requests
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from openai import OpenAI

# ===== CARGAR API KEY DE OPENAI =====
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    st.error("No se encontró la variable OPENAI_API_KEY en el archivo .env")
else:
    client = OpenAI(api_key=OPENAI_API_KEY)

# ===== CONFIGURACIÓN DE MERCADO LIBRE =====
# OJO: para pruebas puedes usar MLM (México) o MLA (Argentina).
# Cuando confirmes el site ID de Panamá, lo cambias aquí.
SITE_ID = "MCO"  # cambiar a "MLPA" si el site existe y funciona para Panamá

st.title("💰 Pignora - Demo con Mercado Libre + IA")

st.markdown(
    """
Esta demo hace tres cosas:

1. Consulta precios reales en Mercado Libre.
2. Calcula un valor base de empeño.
3. Pide a una IA que ajuste el valor y lo explique.
"""
)

# ===== ENTRADAS DEL USUARIO =====
st.subheader("Datos del artículo")

producto = st.text_input("¿Qué artículo quieres tasar? (ej: 'iPhone 11 128GB')")
precio_original = st.number_input("Precio original aproximado (USD)", min_value=10.0, value=500.0, step=10.0)
antiguedad = st.slider("Antigüedad (años)", 0, 15, 2)
condicion = st.slider("Condición (1 = muy mala, 10 = excelente)", 1, 10, 8)
descripcion = st.text_area(
    "Descripción libre del artículo (opcional, se usa para la IA):",
    "iPhone 11, buen estado, batería 85%, con caja, pequeños rayones en la carcasa."
)

if st.button("Calcular valor con mercado + IA"):

    if not producto:
        st.warning("Escribe al menos el nombre del artículo para buscar en Mercado Libre.")
        st.stop()

    # ===== 1. CONSULTA A MERCADO LIBRE =====
    st.subheader("1️⃣ Precios en Mercado Libre")

    search_url = f"https://api.mercadolibre.com/sites/{SITE_ID}/search"
    params = {
        "q": producto,
        "condition": "used",  # buscamos usados, más cercanos al empeño
        "limit": 30
    }

    try:
        resp = requests.get(search_url, params=params)
        data = resp.json()
    except Exception as e:
        st.error(f"Error consultando Mercado Libre: {e}")
        st.stop()

    resultados = data.get("results", [])

    if not resultados:
        st.warning("No se encontraron resultados en Mercado Libre para ese término.")
        st.stop()

    precios = [item["price"] for item in resultados if "price" in item]

    if not precios:
        st.warning("No se encontraron precios válidos en los resultados.")
        st.stop()

    precios_np = np.array(precios)
    promedio = float(np.mean(precios_np))
    mediana = float(np.median(precios_np))
    minimo = float(np.min(precios_np))
    maximo = float(np.max(precios_np))

    st.write(f"Se encontraron **{len(precios)}** precios de referencia.")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Promedio mercado", f"${promedio:,.2f}")
    col2.metric("Mediana mercado", f"${mediana:,.2f}")
    col3.metric("Mínimo", f"${minimo:,.2f}")
    col4.metric("Máximo", f"${maximo:,.2f}")

    # Gráfico de distribución de precios
    fig, ax = plt.subplots()
    ax.hist(precios_np, bins=10)
    ax.set_xlabel("Precio (USD)")
    ax.set_ylabel("Cantidad de publicaciones")
    ax.set_title("Distribución de precios en Mercado Libre")
    st.pyplot(fig)

    # ===== 2. CÁLCULO DEL VALOR BASE DE EMPEÑO =====
    st.subheader("2️⃣ Cálculo de valor base de empeño (modelo simple)")

    # Factor por antigüedad (decrece con los años, mínimo 0.2)
    factor_antiguedad = max(0.2, 1 - 0.08 * antiguedad)
    # Factor por condición (1–10 -> 0.3–1.0)
    factor_condicion = 0.3 + 0.07 * (condicion - 1)
    # Usamos la MEDIANA de mercado como referencia, más robusta que el promedio
    valor_base = mediana * factor_antiguedad * factor_condicion
    # Y un factor de “riesgo empeño” (no prestas el 100% del valor usado)
    factor_riesgo = 0.6
    valor_empeno = valor_base * factor_riesgo

    st.write(f"**Factor antigüedad:** {factor_antiguedad:.2f}")
    st.write(f"**Factor condición:** {factor_condicion:.2f}")
    st.write(f"**Factor riesgo empeño:** {factor_riesgo:.2f}")

    st.metric("Valor base sugerido de empeño", f"${valor_empeno:,.2f}")

    # Gráfico: cómo cambiaría el valor de empeño según la condición
    condiciones = np.arange(1, 11)
    factores_cond = 0.3 + 0.07 * (condiciones - 1)
    valores_por_cond = mediana * factor_antiguedad * factores_cond * factor_riesgo

    fig2, ax2 = plt.subplots()
    ax2.plot(condiciones, valores_por_cond, marker="o")
    ax2.set_xlabel("Condición (1-10)")
    ax2.set_ylabel("Valor de empeño estimado (USD)")
    ax2.set_title("Sensibilidad del valor de empeño a la condición")
    ax2.grid(True)
    st.pyplot(fig2)

    # ===== 3. AJUSTE Y EXPLICACIÓN CON IA =====
    st.subheader("3️⃣ Ajuste y explicación con IA")

    if not OPENAI_API_KEY:
        st.warning("No se puede usar IA porque falta la API key de OpenAI en el archivo .env")
        st.stop()

    prompt = f"""
Eres un tasador experto de casas de empeño en Latinoamérica.

Datos del artículo:
- Producto: {producto}
- Descripción: {descripcion}
- Precio original aproximado: {precio_original:.2f} USD
- Antigüedad: {antiguedad} años
- Condición (1-10): {condicion}

Datos de mercado (Mercado Libre):
- Precio mediano de mercado usado: {mediana:.2f} USD
- Precio promedio de mercado usado: {promedio:.2f} USD
- Rango de precios observados: min {minimo:.2f} USD, max {maximo:.2f} USD.

Cálculo interno del sistema:
- Valor base de empeño calculado: {valor_empeno:.2f} USD

Tarea:
Con estos datos, propone un valor de empeño recomendado para este artículo en un contexto como Panamá, siendo conservador pero competitivo.

Responde en español, en **una sola línea**, con este formato EXACTO:
VALOR_RECOMENDADO: <numero_en_USD> - <explicación breve en 15-30 palabras>.
"""

    with st.spinner("Consultando a la IA para ajustar el valor..."):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un asistente experto en tasación de artículos para casas de empeño en Latinoamérica."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
            )
            texto_ia = response.choices[0].message.content.strip()
        except Exception as e:
            st.error(f"Error consultando la IA: {e}")
            texto_ia = None

    if texto_ia:
        st.write("### Sugerencia de la IA")
        st.info(texto_ia)

    st.caption("Esta demo es solo orientativa. No sustituye un modelo de riesgo real ni criterios regulatorios.")
