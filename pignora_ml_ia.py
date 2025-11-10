import os
import requests
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from openai import OpenAI
from bs4 import BeautifulSoup

# ===== CONFIGURACIÓN INICIAL =====
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

st.set_page_config(page_title="Pignora - Estimador", page_icon="💰")
st.title("💰 Pignora - Estimador de Valor de Empeño")

st.markdown("""
Esta herramienta estima el **valor de empeño** de artículos usados, combinando datos de mercado y ajustes opcionales con IA.
""")

# ===== FUNCIONES =====
def consultar_mercado_libre(producto, site="MCO"):
    """Consulta precios de Mercado Libre."""
    url = f"https://api.mercadolibre.com/sites/{site}/search"
    params = {"q": producto, "condition": "used", "limit": 25}
    try:
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()
        resultados = data.get("results", [])
        precios = [r["price"] for r in resultados if "price" in r]
        return precios if precios else None
    except:
        return None

def scraping_google(producto):
    """Alternativa de scraping simple (público) si falla la API."""
    query = producto.replace(" ", "+")
    url = f"https://www.google.com/search?q={query}+precio+usado"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(resp.text, "html.parser")
        precios = []
        for t in soup.find_all("span"):
            texto = t.get_text()
            if "$" in texto:
                try:
                    valor = float(texto.replace("$", "").replace(",", "").split()[0])
                    if 10 < valor < 10000:
                        precios.append(valor)
                except:
                    continue
        return precios if precios else None
    except Exception as e:
        st.warning(f"Error al hacer scraping: {e}")
        return None

def calcular_empeno(precios, antiguedad, condicion):
    """Modelo de cálculo base."""
    precios_np = np.array(precios)
    mediana = float(np.median(precios_np))
    factor_ant = max(0.2, 1 - 0.08 * antiguedad)
    factor_cond = 0.3 + 0.07 * (condicion - 1)
    valor_base = mediana * factor_ant * factor_cond * 0.6
    return valor_base, mediana

def ajuste_con_ia(producto, descripcion, valor_base, precios_ref):
    """Ajuste opcional con IA (requiere suscripción del usuario)."""
    if not OPENAI_API_KEY:
        st.warning("Esta función requiere una suscripción activa con IA (clave OpenAI).")
        return "Función de IA no disponible."
    
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""
Eres un tasador experto en artículos usados y casas de empeño en Latinoamérica.
Producto: {producto}
Descripción: {descripcion}
Valor base estimado: {valor_base:.2f} USD
Precios de referencia: {min(precios_ref):.2f}-{max(precios_ref):.2f} USD
Da una estimación ajustada (±15%) con una breve justificación de 15–25 palabras.
Formato exacto:
VALOR_FINAL: <número> USD - <comentario breve>.
"""
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Error de IA: {e}"

# ===== INTERFAZ =====
producto = st.text_input("🔹 Artículo a evaluar", "iPhone 11 128GB")
precio_original = st.number_input("Precio original (USD)", value=500.0, step=10.0)
antiguedad = st.slider("Antigüedad (años)", 0, 15, 2)
condicion = st.slider("Condición (1=muy mala, 10=excelente)", 1, 10, 8)
descripcion = st.text_area("Descripción del artículo", "iPhone 11 usado, batería 85%, con caja original.")

if st.button("Calcular valor base"):
    precios = consultar_mercado_libre(producto)
    if not precios:
        st.warning("No se obtuvieron resultados desde Mercado Libre.")
        precios = [precio_original * 0.8, precio_original * 0.9, precio_original]

    valor_base, mediana = calcular_empeno(precios, antiguedad, condicion)

    st.subheader("📊 Resultado inicial")
    st.metric("Valor base estimado", f"${valor_base:,.2f}")
    st.write(f"Mediana de mercado: ${mediana:,.2f}")

    fig, ax = plt.subplots()
    ax.hist(precios, bins=10, color="lightblue", edgecolor="gray")
    ax.set_title("Distribución de precios de referencia")
    st.pyplot(fig)

    # ===== OPCIONES DE AJUSTE =====
    st.markdown("---")
    st.subheader("⚙️ Opciones de ajuste")

    if st.button("🔍 Ajustar búsqueda (web scraping)"):
        precios_scrap = scraping_google(producto)
        if precios_scrap:
            valor_adj, mediana_adj = calcular_empeno(precios_scrap, antiguedad, condicion)
            st.success(f"Nuevo valor estimado: ${valor_adj:,.2f} (basado en scraping web)")
            st.caption("El scraping amplió la muestra de precios para mejorar la estimación.")
        else:
            st.warning("No se encontraron precios mediante scraping.")

    if st.button("🤖 Ajuste con IA (requiere suscripción)"):
        resultado_ia = ajuste_con_ia(producto, descripcion, valor_base, precios)
        st.info(resultado_ia)
        st.caption("La IA analiza contexto y valores para ofrecer una justificación breve.")
