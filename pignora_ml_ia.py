import os
import requests
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

# ===== CONFIGURACIÓN =====
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

SITE_ID = "MCO"  # Colombia; cambiar a MLPA cuando funcione para Panamá

# ===== FUNCIONES =====

def buscar_precios_mercado(producto):
    """Devuelve precios del producto en Mercado Libre o None si falla."""
    search_url = f"https://api.mercadolibre.com/sites/{SITE_ID}/search"
    params = {"q": producto, "condition": "used", "limit": 30}
    try:
        resp = requests.get(search_url, params=params, timeout=8)
        data = resp.json()
        precios = [item["price"] for item in data.get("results", []) if "price" in item]
        if len(precios) < 3:
            return None
        return np.array(precios)
    except Exception:
        return None


def estimar_valor_ia(producto, descripcion, precio_original, antiguedad, condicion, valor_estimado, imagen=None):
    """Solicita a la IA una valoración ajustada."""
    prompt = f"""
Eres un tasador experto de casas de empeño en Latinoamérica.

Datos del artículo:
- Producto: {producto}
- Descripción: {descripcion}
- Precio original aproximado: {precio_original} USD
- Antigüedad: {antiguedad} años
- Condición (1-10): {condicion}
- Valor estimado inicial: {valor_estimado} USD

Analiza el contexto y ajusta el valor a un rango realista para Panamá.
Responde en una sola línea:
VALOR_RECOMENDADO: <USD> - <explicación breve en 15-30 palabras>.
"""

    if not client:
        return "⚠️ No se detectó API key de OpenAI. No se puede usar IA."

    try:
        if imagen:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un experto en tasaciones y empeños."},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": imagen}}
                    ]}
                ],
            )
        else:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un experto en tasaciones y empeños."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
            )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"⚠️ Error consultando la IA: {e}"


# ===== INTERFAZ =====
st.title("💰 Pignora - Tasación inteligente con IA y Mercado Libre")

st.markdown("Selecciona si quieres incluir precios de Mercado Libre o subir una imagen del artículo.")
usar_mercado = st.checkbox("🔍 Consultar precios en Mercado Libre")
subir_foto = st.checkbox("📸 Subir imagen del artículo")

producto = st.text_input("¿Qué artículo quieres tasar? (ej: 'iPhone 11 128GB')")
precio_original = st.number_input("Precio original aproximado (USD)", min_value=10.0, value=500.0)
antiguedad = st.slider("Antigüedad (años)", 0, 15, 2)
condicion = st.slider("Condición (1 = muy mala, 10 = excelente)", 1, 10, 8)
descripcion = st.text_area("Descripción breve:", "Buen estado, con caja, batería al 80%, algunos rayones leves.")
imagen_archivo = st.file_uploader("Sube una foto (opcional, mejora la estimación visual):", type=["jpg", "png", "jpeg"]) if subir_foto else None

if st.button("Calcular valor de empeño"):
    precios_np = None

    # ===== 1. MERCADO LIBRE =====
    if usar_mercado and producto:
        st.subheader("🔹 Consulta de precios en Mercado Libre")
        precios_np = buscar_precios_mercado(producto)
        if precios_np is not None:
            promedio = float(np.mean(precios_np))
            mediana = float(np.median(precios_np))
            minimo = float(np.min(precios_np))
            maximo = float(np.max(precios_np))

            st.write(f"**Precios obtenidos:** {len(precios_np)} resultados.")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Promedio", f"${promedio:,.2f}")
            col2.metric("Mediana", f"${mediana:,.2f}")
            col3.metric("Mínimo", f"${minimo:,.2f}")
            col4.metric("Máximo", f"${maximo:,.2f}")

            fig, ax = plt.subplots()
            ax.hist(precios_np, bins=10)
            ax.set_xlabel("Precio (USD)")
            ax.set_ylabel("Publicaciones")
            ax.set_title("Distribución de precios en Mercado Libre")
            st.pyplot(fig)
        else:
            st.info("No se pudieron obtener precios de Mercado Libre o no hubo resultados.")

    # ===== 2. CÁLCULO BASE =====
    st.subheader("📊 Cálculo base de empeño")

    factor_antiguedad = max(0.2, 1 - 0.08 * antiguedad)
    factor_condicion = 0.3 + 0.07 * (condicion - 1)
    base = (np.median(precios_np) if precios_np is not None else precio_original * 0.4)
    valor_estimado = base * factor_antiguedad * factor_condicion * 0.6

    st.metric("Valor base estimado", f"${valor_estimado:,.2f}")

    # ===== 3. IA =====
    st.subheader("🤖 Ajuste con IA")
    imagen_url = None
    if imagen_archivo:
        img = Image.open(imagen_archivo)
        st.image(img, caption="Imagen subida", use_container_width=True)
        imagen_url = st.file_uploader  # Placeholder para futuras mejoras (upload a servidor)

    texto_ia = estimar_valor_ia(producto, descripcion, precio_original, antiguedad, condicion, valor_estimado, imagen_url)
    st.info(texto_ia)

st.caption("💡 Esta demo combina IA + comparaciones de mercado para estimar valores de empeño de forma referencial.")
