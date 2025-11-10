import os
import requests
import numpy as np
import streamlit as st
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from openai import OpenAI
import pandas as pd
import altair as alt
import re
import time # Para pausas entre peticiones

# ================== CONFIGURACIÓN INICIAL ==================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Pignora - Estimador de Empeño", page_icon="💰", layout="wide")
st.title("💰 Pignora - Estimador de Valor de Empeño")

st.markdown("""
¡Bienvenido a Pignora! Esta herramienta te ayuda a estimar un valor de empeño combinando:

1.  **🏷️ Precios de Mercado:** Busca activamente precios de artículos similares en Mercado Libre (vía API y web scraping).
2.  **📉 Modelo de Depreciación:** Aplica ajustes por antigüedad y condición del artículo.
3.  **🤖 Ajuste Opcional con IA:** Ofrece una evaluación premium para una recomendación más precisa (simulado como $0.99 por evaluación).
""")

# ================== FUNCIONES DE UTILIDAD ==================

TASAS_CAMBIO_A_USD = {
    "MXN": 0.050,
    "COP": 0.00025,
    "ARS": 0.0012,
    "USD": 1.0,
    "CLP": 0.0010,
    "PEN": 0.27,
    "UYU": 0.025,
    "BRL": 0.20,
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

def buscar_mercado_libre_api(query: str):
    sites = {
        "MLM": "México", "MCO": "Colombia", "MLA": "Argentina",
        "MLC": "Chile", "MPE": "Perú", "MLU": "Uruguay", "MLB": "Brasil"
    }
    todos_precios_usd = []
    todos_resultados_crudos = []
    sitio_usado = None

    st.subheader("🛠️ Diagnóstico API Mercado Libre:")
    st.write(f"Buscando con query: `{query}`")

    for site_id, pais_nombre in sites.items():
        url = f"https://api.mercadolibre.com/sites/{site_id}/search"
        params = {"q": query, "condition": "used", "limit": 20}
        st.write(f"Intentando API en {pais_nombre} ({site_id}). URL: `{url}?q={query}&condition=used&limit=20`")
        
        try:
            resp = requests.get(url, params=params, timeout=10) # Aumentar timeout
            st.write(f"Status API {site_id}: {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
            resultados = data.get("results", [])
            st.write(f"Resultados API {site_id} encontrados: {len(resultados)}")

            precios_site = []
            for r in resultados:
                if "price" in r and "currency_id" in r:
                    precio_usd = convertir_a_usd(r["price"], r["currency_id"])
                    if precio_usd > 0:
                        precios_site.append(precio_usd)
            
            if precios_site:
                todos_precios_usd.extend(precios_site)
                for item in resultados[:5]:
                     if "price" in item and "currency_id" in item:
                        todos_resultados_crudos.append({
                            "Título": item.get("title", "")[:60] + "...",
                            "Precio Original": f"{item.get('price', 0.0):,.2f} {item.get('currency_id', '')}",
                            "Precio USD": convertir_a_usd(item.get("price", 0.0), item.get("currency_id", "")),
                            "Link": item.get("permalink", ""),
                            "Sitio": site_id
                        })
                sitio_usado = site_id
                # st.success(f"Éxito en API de {pais_nombre}.") # Descomentar para ver éxito inmediato
                break # Para la demo, parar si encuentra resultados
        except requests.exceptions.Timeout:
            st.warning(f"Timeout al conectar con API de ML en {pais_nombre}.")
        except requests.exceptions.RequestException as e:
            st.warning(f"Error de petición API para {pais_nombre} ({site_id}): {e}")
            if resp.status_code == 404:
                st.info("Comprueba si la URL de la API es correcta o si el site_id es válido.")
            elif resp.status_code == 400:
                st.info("Problema con la query. Intenta simplificarla.")
        except Exception as e:
            st.error(f"Error inesperado al buscar en {pais_nombre} (API): {e}")
        time.sleep(1) # Pequeña pausa entre peticiones para evitar bloqueos

    return todos_precios_usd, todos_resultados_crudos, sitio_usado


def buscar_mercado_libre_scraping(query: str):
    slug = query.replace(" ", "-")
    url = f"https://listado.mercadolibre.com.mx/{slug}" 
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.mercadolibre.com.mx/",
        "DNT": "1",
        "Connection": "keep-alive"
    }

    precios_usd = []
    st.subheader("🛠️ Diagnóstico Web Scraping Mercado Libre:")
    st.write(f"Intentando scraping en URL: `{url}`")
    
    try:
        resp = requests.get(url, headers=headers, timeout=15) # Aumentar timeout aún más
        st.write(f"Status Web Scraping: {resp.status_code}")
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # --- NUEVOS SELECTORES PARA PROBAR (Ajusta ESTO según tu inspección) ---
        # 1. Selector principal (común)
        price_selectors = [
            "span.andes-money-amount__fraction", # Original y muy común
            "div.ui-search-price__second-line span.andes-money-amount__fraction", # Otro común
            "span.andes-money-amount__parts:first-child .andes-money-amount__fraction", # Visto en algunos layouts
            "span[data-testid='price-part']", # A veces usan data-attributes
            ".ui-search-item__group__element.ui-search-item__group__element--price span.andes-money-amount__fraction", # Más específico
            "div.ui-search-item__group__element--price span.andes-money-amount__fraction", # Otra variante
            "span.price-tag-fraction", # Un selector antiguo que a veces resurge
            ".andes-money-amount__fraction" # Selector genérico si nada más funciona (puede capturar otros elementos)
        ]
        
        price_tags = []
        for selector in price_selectors:
            found_tags = soup.select(selector)
            if found_tags:
                st.write(f"✔️ Selector `{selector}` encontró {len(found_tags)} elementos.")
                price_tags.extend(found_tags)
                # Para la demo, puedes parar aquí si ya encontraste algunos
                # break 
            else:
                st.write(f"❌ Selector `{selector}` no encontró elementos.")
        
        if not price_tags:
            st.info("Scraping: Ninguno de los selectores directos encontró elementos de precio. Intentando fallback...")
            # Fallback con expresiones regulares en todo el HTML si los selectores fallan
            price_matches = re.findall(r'\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)', resp.text)
            st.write(f"Fallback encontró {len(price_matches)} coincidencias con regex.")
            for match in price_matches:
                clean_price = match.replace('.', '').replace(',', '').strip() # Limpia formatos MXN/COP
                try:
                    val_mxn = float(clean_price)
                    if 50 < val_mxn < 5000000:
                        precios_usd.append(convertir_a_usd(val_mxn, "MXN")) # Asume MXN para el scraping
                except ValueError:
                    continue
            if precios_usd:
                st.write(f"Fallback Regex encontró {len(precios_usd)} precios válidos.")
                return precios_usd
            else:
                st.warning("Scraping: Fallback con Regex tampoco encontró precios válidos.")
                return []


        # Procesar los tags encontrados por los selectores
        for span in price_tags:
            txt = span.get_text(strip=True).replace(".", "").replace(",", "")
            try:
                val_mxn = float(txt)
                if 50 < val_mxn < 5000000:
                    precios_usd.append(convertir_a_usd(val_mxn, "MXN"))
            except ValueError:
                continue
        st.write(f"Scraping finalizó. Encontrados {len(precios_usd)} precios válidos.")

    except requests.exceptions.Timeout:
        st.warning("⚠️ Scraping: Tiempo de espera agotado al intentar acceder a Mercado Libre.")
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Scraping: Error de red o HTTP al intentar acceder a Mercado Libre: {e}. URL: {url}")
        if "403 Client Error: Forbidden" in str(e):
            st.warning("Mercado Libre podría haber bloqueado la petición. Intenta cambiar el User-Agent o usar un proxy.")
    except Exception as e:
        st.error(f"⚠️ Scraping: Error inesperado durante el proceso: {e}")

    return precios_usd

# ... (El resto de las funciones: calcular_valor_empeno, generar_comentario_ia son las mismas) ...

# ================== INTERFAZ DE USUARIO (Streamlit) ==================

with st.sidebar:
    st.header("⚙️ Configuración del Artículo")
    categoria = st.selectbox(
        "Tipo de artículo",
        [
            "Laptop", "iPhone", "Smartphone Android", "Consola de videojuegos",
            "Televisor", "Herramienta eléctrica", "Joya / Reloj", "Otro",
        ],
    )
    modelo = st.text_input("Modelo / Referencia (ej: 'Dell Vostro 3500', 'iPhone 11 128GB')", "PlayStation 4")
    descripcion = st.text_area(
        "Descripción del artículo",
        "Buen estado general, uso moderado, incluye cargador y caja, pequeños rayones en pantalla.",
    )

    st.subheader("📊 Detalles de Valoración")
    precio_original = st.number_input(
        "Precio original (nuevo, USD)", min_value=10.0, value=500.0, step=10.0, format="%.2f"
    )
    antiguedad = st.slider("Antigüedad (años)", 0, 10, 4)
    condicion = st.slider("Condición (1 = muy mala, 10 = excelente)", 1, 10, 7)

    st.subheader("🌐 Fuentes de Datos")
    col_api, col_scrap = st.columns(2)
    with col_api:
        usar_api_ml = st.checkbox("API Mercado Libre", value=True, help="Busca precios a través de la API oficial.")
    with col_scrap:
        usar_scraping_ml = st.checkbox("Scraping Web ML", value=True, help="Complementa con búsqueda directa en la web de Mercado Libre.")

    st.subheader("💡 Funcionalidad Premium")
    usar_ia_premium = st.checkbox(
        "Activar IA premium (simula costo de $0.99)", value=False,
        help="Obtén una recomendación final y justificación de un tasador IA. (En un entorno real, esto tendría un costo)."
    )
    if usar_ia_premium:
        st.info("Simulando cobro de $0.99 por esta evaluación de IA.")


st.markdown("---")
if st.button("🚀 Calcular Estimación de Empeño", type="primary", use_container_width=True):
    if not modelo and categoria == "Otro":
        st.error("❌ Por favor, especifica al menos un modelo o selecciona una categoría conocida para la búsqueda.")
        st.stop()

    query = construir_query(categoria, modelo)
    st.subheader(f"🔍 Evaluando: '{query}'")

    col_ml_api, col_ml_scrap = st.columns(2)
    precios_totales_usd = []

    with col_ml_api:
        st.markdown("##### 1️⃣ Búsqueda en Mercado Libre (API)")
        if usar_api_ml:
            with st.spinner("Buscando en Mercado Libre vía API..."):
                precios_api_usd, resultados_crudos_api, site_usado = buscar_mercado_libre_api(query)
                if precios_api_usd:
                    st.success(f"✔️ Encontrados {len(precios_api_usd)} precios en el sitio {site_usado if site_usado else 'varios'} (vía API).")
                    if resultados_crudos_api:
                        df_api = pd.DataFrame(resultados_crudos_api)
                        st.dataframe(df_api, use_container_width=True, hide_index=True,
                                     column_config={"Link": st.column_config.LinkColumn("Link", display_text="Ver →")})
                    precios_totales_usd.extend(precios_api_usd)
                else:
                    st.info("No se encontraron resultados relevantes vía API.")
        else:
            st.info("API de Mercado Libre desactivada.")


    with col_ml_scrap:
        st.markdown("##### 2️⃣ Búsqueda en Mercado Libre (Web Scraping)")
        if usar_scraping_ml:
            with st.spinner("Buscando en Mercado Libre vía Web Scraping (México)..."):
                precios_scrap_usd = buscar_mercado_libre_scraping(query)
                if precios_scrap_usd:
                    st.success(f"✔️ Encontrados {len(precios_scrap_usd)} precios en ML México (vía Web Scraping).")
                    df_scrap = pd.DataFrame([{"Fuente": "ML Web MX", "Precio USD": f"{p:,.2f}"} for p in precios_scrap_usd[:10]])
                    st.dataframe(df_scrap, use_container_width=True, hide_index=True)
                    precios_totales_usd.extend(precios_scrap_usd)
                else:
                    st.info("No se encontraron precios relevantes vía Web Scraping. Esto puede ocurrir si el sitio ha cambiado su estructura o fue bloqueado.")
        else:
            st.info("Web Scraping desactivado.")
    
    st.markdown("---")

    if not precios_totales_usd:
        st.error("❌ Lo sentimos, no se pudo obtener ningún precio de referencia. Intenta ajustar el modelo o la descripción y/o verifica que las fuentes estén activas.")
        st.stop()

    st.subheader("3️⃣ Análisis de Mercado y Cálculo Base")
    
    precios_filtrados = [p for p in precios_totales_usd if p is not None and p > 0]
    if not precios_filtrados:
        st.error("❌ No hay precios válidos para calcular la estimación. Revisa las fuentes de datos.")
        st.stop()

    stats = calcular_valor_empeno(precios_filtrados, antiguedad, condicion)

    if stats is None:
        st.error("❌ No se pudo calcular el valor de empeño. Esto puede ocurrir si no hay suficientes datos válidos.")
        st.stop()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Mediana de Mercado (USD)", f"${stats['mediana']:,.2f}")
    col2.metric("📊 Promedio de Mercado (USD)", f"${stats['promedio']:,.2f}")
    col3.metric("⬇️ Mínimo Encontrado (USD)", f"${stats['minimo']:,.2f}")
    col4.metric("⬆️ Máximo Encontrado (USD)", f"${stats['maximo']:,.2f}")

    st.markdown("#### Factores de Ajuste Aplicados:")
    col_fact1, col_fact2, col_fact3 = st.columns(3)
    col_fact1.info(f"**Factor por Antigüedad ({antiguedad} años):** {stats['factor_antiguedad']:.2f}")
    col_fact2.info(f"**Factor por Condición ({condicion}/10):** {stats['factor_condicion']:.2f}")
    col_fact3.info(f"**Factor de Empeño (Riesgo/Ganancia):** {stats['factor_riesgo_ganancia']:.2f}")

    st.markdown("---")
    st.subheader(f"✅ Valor Base Sugerido de Empeño: **${stats['valor_base']:,.2f} USD**")
    st.markdown("Este valor es una estimación inicial aplicando los factores de depreciación y el margen de empeño.")

    st.markdown("#### Distribución de Precios de Mercado Encontrados (USD)")
    df_precios = pd.DataFrame({'Precio (USD)': precios_filtrados})
    
    min_chart_price = df_precios['Precio (USD)'].quantile(0.05) if not df_precios.empty else 0
    max_chart_price = df_precios['Precio (USD)'].quantile(0.95) if not df_precios.empty else 1000
    
    chart = alt.Chart(df_precios).mark_bar().encode(
        alt.X('Precio (USD)', bin=alt.Bin(maxbins=20), scale=alt.Scale(domain=[min_chart_price, max_chart_price])),
        alt.Y('count()', title='Frecuencia'),
        tooltip=['Precio (USD)', 'count()']
    ).properties(
        title='Histograma de Precios Convertidos a USD (Rango principal)'
    )
    st.altair_chart(chart, use_container_width=True)

    st.subheader("4️⃣ Ajuste con Inteligencia Artificial Premium (Opcional)")

    if usar_ia_premium:
        comentario_ia = generar_comentario_ia(
            query, descripcion, precio_original, antiguedad, condicion, stats
        )
        st.markdown("---")
        if "VALOR_RECOMENDADO_FINAL:" in comentario_ia:
            try:
                parts = comentario_ia.split("VALOR_RECOMENDADO_FINAL:")
                valor_str = parts[1].split('-')[0].strip().replace("$", "").replace(",", "")
                valor_str_clean = re.sub(r'[^\d.]+', '', valor_str)
                valor_ia = float(valor_str_clean)
                justificacion = parts[1].split('-', 1)[1].strip()
                st.success(f"**Recomendación IA Premium:** **${valor_ia:,.2f} USD** - *{justificacion}*")
            except Exception as e:
                st.warning(f"La IA respondió, pero no pude parsear el formato: {comentario_ia}. Error: {e}")
        else:
            st.warning(comentario_ia)
        st.caption("💳 Esta evaluación se considera una consulta premium (simulando un costo de $0.99).")
    else:
        st.info("💡 Activa la **IA Premium** en la barra lateral para obtener una recomendación final y justificación más personalizada.")

    st.markdown("---")
    st.caption("⚠️ **Descargo de Responsabilidad:** Esta herramienta es una *demostración* y proporciona una estimación orientativa. No reemplaza una tasación profesional, políticas internas, ni criterios regulatorios de una casa de empeño real. Las tasas de cambio y los precios de mercado pueden variar.")