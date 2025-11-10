import os
import io
import requests
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

# ===== CONFIGURACIÓN INICIAL =====
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    st.error("No se encontró la variable OPENAI_API_KEY en el archivo .env o en Streamlit Secrets.")
    st.stop()
else:
    client = OpenAI(api_key=OPENAI_API_KEY)

st.set_page_config(page_title="Pignora", page_icon="💰")
st.title("💰 Pignora - IA + Comparaciones de Mercado")

st.markdown("""
Esta demo permite estimar valores de empeño basados en:
1. **Precios reales** (Mercado Libre, si está disponible).
2. **Factores técnicos** (antigüedad, condición).
3. **Ajuste con IA**, que explica y refina la estimación.
""")

# ===== FUNCIONES AUXILIARES =====

def consultar_precios_mercado(producto: str, site_id="MCO"):
    """Consulta precios en Mercado Libre; devuelve lista de precios o [] si falla."""
    url = f"https://api.mercadolibre.com/sites/{site_id}/search"
    params = {"q": producto, "condition": "used", "limit": 30}
    try:
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()
        resultados = data.get("results", [])
        precios = [item["price"] for item in resultados if "price" in item]
        return precios
    except Exception:
        return []

def estimar_valor_base(precio_ref, antiguedad, condicion):
    """Modelo básico de depreciación."""
    factor_antiguedad = max(0.2, 1 - 0.08 * antiguedad)
    factor_condicion = 0.3 + 0.07 * (condicion - 1)
    factor_riesgo = 0.6
    return precio_ref * factor_antiguedad * factor_condicion * factor_riesgo

def estimar_valor_ia(producto, descripcion, precio_original, antiguedad, condicion, valor_base, imagen_bytes=None):
    """Consulta la IA para refinar la estimación."""
    prompt = f"""
Eres un tasador experto de casas de empeño en Latinoamérica.

Datos del artículo:
- Producto: {producto}
- Descripción: {descripcion}
- Precio original aproximado: {precio_original:.2f} USD
- Antigüedad: {antiguedad} años
- Condición (1-10): {condicion}
- Valor base calculado: {valor_base:.2f} USD

Tarea:
Propón un valor de empeño recomendado para Panamá, conservador pero competitivo.
Responde en español, en **una sola línea**, con el formato:
VALOR_RECOMENDADO: <numero_en_USD> - <explicación breve en 15-30 palabras>.
"""

    try:
        if imagen_bytes:
            # Si hay imagen, usar GPT-4o con input visual
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un experto tasador de artículos empeñados en LATAM."},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": imagen_bytes}}
                    ]}
                ],
                temperature=0.3,
            )
        else:
            # Sin imagen
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un experto tasador de artículos empeñados en LATAM."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
            )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"⚠️ Error consultando la IA: {e}"

# ===== ENTRADAS =====
st.subheader("📦 Datos del artículo")

producto = st.text_input("¿Qué artículo quieres tasar? (ej: 'iPhone 11 128GB')")
precio_original = st.number_input("Precio original aproximado (USD)", min_value=10.0, value=500.0, step=10.0)
antiguedad = st.slider("Antigüedad (años)", 0, 15, 2)
condicion = st.slider("Condición (1 = muy mala, 10 = excelente)", 1, 10, 8)
descripcion = st.text_area("Descripción libre del artículo (opcional)", "iPhone 11, buen estado, batería 85%, con caja.")
imagen_archivo = st.file_uploader("📷 Sube una imagen del artículo (opcional)", type=["jpg", "jpeg", "png"])

if st.button("Calcular valor estimado"):
    if not producto:
        st.warning("Debes ingresar al menos el nombre del producto.")
        st.stop()

    # ===== 1. CONSULTA MERCADO LIBRE =====
    st.subheader("🛒 Consulta de precios en Mercado Libre")
    precios = consultar_precios_mercado(producto)

    if precios:
        precios_np = np.array(precios)
        mediana = float(np.median(precios_np))
        promedio = float(np.mean(precios_np))
        minimo, maximo = float(np.min(precios_np)), float(np.max(precios_np))

        st.write(f"Se encontraron **{len(precios)}** precios válidos.")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Promedio", f"${promedio:,.2f}")
        col2.metric("Mediana", f"${mediana:,.2f}")
        col3.metric("Mínimo", f"${minimo:,.2f}")
        col4.metric("Máximo", f"${maximo:,.2f}")

        fig, ax = plt.subplots()
        ax.hist(precios_np, bins=10, color="steelblue", alpha=0.7)
        ax.set_xlabel("Precio (USD)")
        ax.set_ylabel("Publicaciones")
        ax.set_title("Distribución de precios")
        st.pyplot(fig)
        precio_ref = mediana
    else:
        st.info("No se pudo obtener información de Mercado Libre. Se usará el precio original como referencia.")
        precio_ref = precio_original * 0.8  # aproximación

    # ===== 2. CÁLCULO BASE =====
    st.subheader("📊 Cálculo base de empeño")
    valor_base = estimar_valor_base(precio_ref, antiguedad, condicion)
    st.metric("Valor base estimado", f"${valor_base:,.2f}")

    # ===== 3. IA =====
    st.subheader("🤖 Ajuste con IA")

    imagen_url = None
    if imagen_archivo:
        img = Image.open(imagen_archivo)
        st.image(img, caption="Imagen subida", use_container_width=True)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        imagen_bytes = buffer.getvalue()
        imagen_url = "data:image/png;base64," + buffer.getvalue().hex()
    else:
        imagen_bytes = None

    texto_ia = estimar_valor_ia(producto, descripcion, precio_original, antiguedad, condicion, valor_base, imagen_bytes)
    st.info(texto_ia)

    st.caption("💡 Esta demo combina IA + comparaciones de mercado para estimar valores de empeño de forma referencial.")
