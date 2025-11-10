import os
import requests
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from openai import OpenAI

# ================== CONFIGURACIÓN ==================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Pignora", page_icon="💰")
st.title("💰 Pignora - Estimador de Valor de Empeño")

st.markdown("""
Esta herramienta estima un valor de empeño combinando:

1. 🏷️ Precios de mercado (Mercado Libre API + scraping web).  
2. 📉 Modelo simple de depreciación por antigüedad y condición.  
3. 🤖 Ajuste opcional con IA **premium** (simulado como $0.99 por evaluación).  
""")

# ================== ENTRADAS DEL USUARIO ==================

categoria = st.selectbox(
    "Tipo de artículo",
    [
        "Laptop",
        "iPhone",
        "Smartphone Android",
        "Consola de videojuegos",
        "Televisor",
        "Herramienta eléctrica",
        "Joya / Reloj",
        "Otro",
    ],
)

modelo = st.text_input("Modelo / referencia (ej: 'Dell Vostro 3500', 'iPhone 11 128GB')")
descripcion = st.text_area(
    "Descripción del artículo",
    "Buen estado general, uso moderado, incluye cargador y caja.",
)

precio_original = st.number_input(
    "Precio original (USD)", min_value=10.0, value=500.0, step=10.0
)

antiguedad = st.slider("Antigüedad (años)", 0, 15, 2)
condicion = st.slider("Condición (1 = muy mala, 10 = excelente)", 1, 10, 8)

usar_api_ml = st.checkbox("Usar API de Mercado Libre", value=True)
usar_scraping_ml = st.checkbox("Complementar con scraping de Mercado Libre web", value=True)

usar_ia_premium = st.checkbox(
    "Activar IA premium ($0.99 por evaluación)", value=False,
    help="Solo disponible para clientes suscritos o pago por evaluación."
)

# ================== FUNCIONES ==================

def construir_query(categoria: str, modelo: str) -> str:
    base = categoria if categoria != "Otro" else ""
    texto = (base + " " + modelo).strip()
    return texto if texto else modelo


def buscar_mercado_libre_api(query: str):
    """
    Busca precios usados en varios sitios de Mercado Libre (API oficial).
    Intenta México, Colombia y Argentina hasta encontrar resultados.
    Devuelve: (lista_precios, lista_resultados_crudos)
    """
    sites = ["MLM", "MCO", "MLA"]  # México, Colombia, Argentina
    for site in sites:
        url = f"https://api.mercadolibre.com/sites/{site}/search"
        params = {"q": query, "condition": "used", "limit": 25}
        try:
            resp = requests.get(url, params=params, timeout=8)
            data = resp.json()
            resultados = data.get("results", [])
            precios = [r["price"] for r in resultados if "price" in r]
            if precios:
                return precios, resultados, site
        except Exception:
            continue
    return [], [], None


def buscar_mercado_libre_scraping(query: str):
    """
    Scraping sencillo de la web de Mercado Libre México.
    No es perfecto, pero intenta extraer algunos precios visibles.
    """
    slug = query.replace(" ", "-")
    url = f"https://listado.mercadolibre.com.mx/{slug}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.mercadolibre.com.mx/",
    }

    precios = []
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        # Los precios suelen estar en spans con esta clase
        for span in soup.select("span.andes-money-amount__fraction"):
            txt = span.get_text(strip=True)
            try:
                val = float(txt.replace(".", "").replace(",", ""))
                if 10 < val < 20000:
                    precios.append(val)
            except:
                continue
    except Exception:
        pass

    return precios


def calcular_valor_empeno(precios, antiguedad, condicion):
    precios_np = np.array(precios)
    mediana = float(np.median(precios_np))
    promedio = float(np.mean(precios_np))
    minimo = float(np.min(precios_np))
    maximo = float(np.max(precios_np))

    # modelo simple de depreciación
    factor_antiguedad = max(0.2, 1 - 0.08 * antiguedad)  # cae 8% por año, mínimo 20%
    factor_condicion = 0.3 + 0.07 * (condicion - 1)      # de 0.3 a 1.0
    factor_riesgo = 0.6                                  # prestas ~60% de ese valor

    valor_base = mediana * factor_antiguedad * factor_condicion * factor_riesgo

    return {
        "mediana": mediana,
        "promedio": promedio,
        "minimo": minimo,
        "maximo": maximo,
        "valor_base": valor_base,
        "factor_antiguedad": factor_antiguedad,
        "factor_condicion": factor_condicion,
        "factor_riesgo": factor_riesgo,
    }


def generar_comentario_ia(query, descripcion, precio_original, antiguedad, condicion, stats):
    if not client:
        return "⚠️ IA no disponible: no hay API key configurada."

    prompt = f"""
Eres un tasador experto de casas de empeño en Latinoamérica.

Artículo:
- Búsqueda base: {query}
- Descripción: {descripcion}
- Precio original: {precio_original:.2f} USD
- Antigüedad: {antiguedad} años
- Condición: {condicion}/10

Datos de mercado estimados:
- Mediana: {stats['mediana']:.2f} USD
- Promedio: {stats['promedio']:.2f} USD
- Rango: {stats['minimo']:.2f} - {stats['maximo']:.2f} USD

Valor base calculado por el sistema (antes de IA): {stats['valor_base']:.2f} USD.

Tarea:
Propón un valor de empeño final realista (para Panamá o similar en Latam)
y justifica brevemente en máximo 25 palabras.

Formato EXACTO de respuesta:
VALOR_RECOMENDADO: <número en USD> - <comentario breve>.
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Eres un tasador conservador pero competitivo para casas de empeño en Latinoamérica.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.35,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Error consultando la IA: {e}"


# ================== LÓGICA PRINCIPAL ==================

if st.button("Calcular estimación"):
    if not modelo and categoria == "Otro":
        st.warning("Especifica al menos un modelo o usa una categoría conocida.")
        st.stop()

    query = construir_query(categoria, modelo)

    precios_api = []
    resultados_api = []
    site_usado = None

    if usar_api_ml:
        st.subheader("1️⃣ Buscando en Mercado Libre (API)")
        precios_api, resultados_api, site_usado = buscar_mercado_libre_api(query)
        if precios_api:
            st.success(f"Se encontraron {len(precios_api)} precios vía API (site {site_usado}).")
            # tabla con algunos resultados
            tabla = []
            for r in resultados_api[:10]:
                tabla.append(
                    {
                        "Título": r.get("title", "")[:50],
                        "Precio": r.get("price", 0.0),
                        "Moneda": r.get("currency_id", ""),
                        "Link": r.get("permalink", ""),
                    }
                )
            st.write("Resultados de Mercado Libre (API):")
            st.dataframe(tabla, use_container_width=True)
        else:
            st.info("No se encontraron resultados vía API, se intentará con scraping si está activado.")

    precios_scrap = []
    if usar_scraping_ml:
        st.subheader("2️⃣ Buscando en Mercado Libre (web scraping)")
        precios_scrap = buscar_mercado_libre_scraping(query)
        if precios_scrap:
            st.success(f"Se encontraron {len(precios_scrap)} precios vía scraping web (ML México).")
            # tabla simple de precios
            st.write("Precios encontrados por scraping (aproximados):")
            st.dataframe(
                [{"Precio": p, "Fuente": "ML Web MX"} for p in precios_scrap[:20]],
                use_container_width=True,
            )
        else:
            st.info("No se encontraron precios usando scraping o el HTML cambió.")

    # combinar fuentes
    precios_totales = []
    precios_totales.extend(precios_api)
    precios_totales.extend(precios_scrap)

    if not precios_totales:
        st.error("❌ No se pudo obtener ningún precio de referencia. Intenta con otro modelo o categoría.")
        st.stop()

    # ================== CÁLCULO BASE ==================
    st.subheader("3️⃣ Cálculo base de valor de empeño")

    stats = calcular_valor_empeno(precios_totales, antiguedad, condicion)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Mediana mercado", f"${stats['mediana']:,.2f}")
    col2.metric("Promedio mercado", f"${stats['promedio']:,.2f}")
    col3.metric("Mínimo", f"${stats['minimo']:,.2f}")
    col4.metric("Máximo", f"${stats['maximo']:,.2f}")

    st.write(f"**Factor antigüedad:** {stats['factor_antiguedad']:.2f}")
    st.write(f"**Factor condición:** {stats['factor_condicion']:.2f}")
    st.write(f"**Factor riesgo empeño:** {stats['factor_riesgo']:.2f}")

    st.metric("Valor base sugerido de empeño", f"${stats['valor_base']:,.2f}")

    # ================== IA PREMIUM ==================
    st.subheader("4️⃣ IA premium (opcional)")

    if usar_ia_premium:
        if not client:
            st.error("No hay API key configurada. La IA premium no está disponible en este entorno.")
        else:
            with st.spinner("Consultando IA (simulando cobro de $0.99 por evaluación)..."):
                comentario = generar_comentario_ia(
                    query, descripcion, precio_original, antiguedad, condicion, stats
                )
            st.info(comentario)
            st.caption("💳 Esta evaluación se considera una consulta premium (ej. $0.99).")
    else:
        st.caption("💡 Activa la IA premium para obtener un valor recomendado y comentario justificativo en una sola línea.")

    st.caption("⚠️ Esta herramienta es orientativa y no reemplaza políticas internas ni criterios regulatorios de una casa de empeño real.")
