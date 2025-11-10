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
import time

# ================== CONFIGURACIÓN INICIAL ==================
load_dotenv()

# --- CLAVES API ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# CLAVE IMPORTANTE PARA MERCADO LIBRE:
# Si tienes una, reemplaza 'YOUR_MERCADOLIBRE_APP_ID_HERE' con tu App ID real.
# Puedes obtenerla en https://developers.mercadolibre.com.ar/es_ar/aplicaciones
# Si no la tienes, el código intentará sin ella, pero el 403 es probable.
ML_APP_ID = os.getenv("ML_APP_ID", "YOUR_MERCADOLIBRE_APP_ID_HERE") 
# También puedes ponerla directamente aquí si no usas .env para ML_APP_ID:
# ML_APP_ID = "1234567890123456" # Ejemplo: ¡Reemplaza con tu ID real!

# Inicializar cliente de OpenAI solo si la API Key está presente
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

# Tasas de cambio simuladas (solo para la demo - en producción, usar una API real)
# Estas tasas son para convertir a USD
TASAS_CAMBIO_A_USD = {
    "MXN": 0.050,
    "COP": 0.00025,
    "ARS": 0.0012,
    "USD": 1.0,
    "CLP": 0.0010,
    "PEN": 0.27,
    "UYU": 0.025,
    "BRL": 0.20,
    "VES": 0.000000028, # Venezuela, muy volátil
    "BOB": 0.14, # Bolivia
    "PYG": 0.00013, # Paraguay
    "DOP": 0.017, # Rep. Dominicana
    "GTQ": 0.13, # Guatemala
    "HNL": 0.040, # Honduras
    "NIO": 0.027, # Nicaragua
    "PAB": 1.0, # Panamá
    "CRC": 0.0019, # Costa Rica
    "SVC": 0.11, # El Salvador
}

def convertir_a_usd(precio: float, moneda_origen: str) -> float:
    """Convierte un precio de su moneda original a USD usando tasas simuladas."""
    moneda_origen = moneda_origen.upper()
    tasa = TASAS_CAMBIO_A_USD.get(moneda_origen)
    if tasa:
        return precio * tasa
    return precio # Retorna el precio original si la moneda no está en la tabla (asumiendo que ya es USD)

def construir_query(categoria: str, modelo: str) -> str:
    """Construye la cadena de búsqueda para Mercado Libre."""
    base = categoria if categoria != "Otro" else ""
    texto = (base + " " + modelo).strip()
    return texto if texto else modelo

def buscar_mercado_libre_api(query: str):
    """
    Busca precios en Mercado Libre usando la API oficial.
    Intenta en varios países hasta encontrar resultados.
    Devuelve precios ya convertidos a USD.
    """
    sites = {
        "MLM": "México", "MCO": "Colombia", "MLA": "Argentina",
        "MLC": "Chile", "MPE": "Perú", "MLU": "Uruguay", "MLB": "Brasil",
        "MLV": "Venezuela", "MLB": "Bolivia", "MLP": "Paraguay", # Más sitios
        "MLD": "Dominicana", "MLG": "Guatemala", "MLH": "Honduras",
        "MLN": "Nicaragua", "MLP": "Panamá", "MLCR": "Costa Rica", "MLS": "El Salvador"
    }
    todos_precios_usd = []
    todos_resultados_crudos = []
    sitio_usado = None

    st.subheader("🛠️ Diagnóstico API Mercado Libre:")
    st.write(f"Buscando con query: `{query}`")

    # Headers para la petición API
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }
    
    # Añadir el App-ID a los parámetros si está definido y no es el placeholder
    base_params = {"q": query, "condition": "used", "limit": 20}
    if ML_APP_ID and ML_APP_ID != "YOUR_MERCADOLIBRE_APP_ID_HERE":
        base_params["app_id"] = ML_APP_ID
    else:
        st.warning("⚠️ No se ha configurado un `ML_APP_ID` real. Las peticiones a la API de Mercado Libre pueden ser rechazadas (Error 403).")
        st.info("Para obtener un `ML_APP_ID`, crea una aplicación en tu cuenta de desarrollador de Mercado Libre: `https://developers.mercadolibre.com.ar/es_ar/aplicaciones`")


    for site_id, pais_nombre in sites.items():
        url = f"https://api.mercadolibre.com/sites/{site_id}/search"
        params = base_params.copy() # Usar una copia para cada sitio
        
        st.write(f"Intentando API en {pais_nombre} ({site_id}). URL: `{url}?q={query}&condition=used&limit=20`")
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10) # Pasar headers
            st.write(f"Status API {site_id}: {resp.status_code}")
            
            # Si hay un error, mostrar el contenido de la respuesta para más detalles
            if resp.status_code != 200:
                st.write(f"Contenido de la respuesta de error de ML: `{resp.text[:500]}`") # Mostrar parte del error
            
            resp.raise_for_status() # Lanza una excepción si el status_code no es 2xx
            data = resp.json()
            resultados = data.get("results", [])
            st.write(f"Resultados API {site_id} encontrados: {len(resultados)}")

            precios_site = []
            for r in resultados:
                if "price" in r and "currency_id" in r:
                    precio_usd = convertir_a_usd(r["price"], r["currency_id"])
                    if precio_usd is not None and precio_usd > 0: # Asegurarse que la conversión fue exitosa y > 0
                        precios_site.append(precio_usd)
            
            if precios_site:
                todos_precios_usd.extend(precios_site)
                for item in resultados[:5]: # Limitar a 5 para la tabla de la demo
                     if "price" in item and "currency_id" in item:
                        todos_resultados_crudos.append({
                            "Título": item.get("title", "")[:60] + "...",
                            "Precio Original": f"{item.get('price', 0.0):,.2f} {item.get('currency_id', '')}",
                            "Precio USD": convertir_a_usd(item.get("price", 0.0), item.get("currency_id", "")),
                            "Link": item.get("permalink", ""),
                            "Sitio": site_id
                        })
                sitio_usado = site_id
                # break # Para la demo, puedes comentar esta línea para buscar en más sitios si quieres
        except requests.exceptions.Timeout:
            st.warning(f"Timeout al conectar con API de ML en {pais_nombre}.")
        except requests.exceptions.RequestException as e:
            st.warning(f"Error de petición API para {pais_nombre} ({site_id}): {e}")
            if resp.status_code == 404:
                st.info("La URL de la API o el `site_id` podrían ser incorrectos.")
            elif resp.status_code == 400:
                st.info("La query podría ser inválida. Intenta simplificarla.")
            elif resp.status_code == 403:
                st.error("¡Acceso Denegado! Mercado Libre está bloqueando la petición. Revisa tu `ML_APP_ID`.")
        except Exception as e:
            st.error(f"Error inesperado al buscar en {pais_nombre} (API): {e}")
        time.sleep(1.5) # Pausa entre peticiones para evitar bloqueos

    return todos_precios_usd, todos_resultados_crudos, sitio_usado


def buscar_mercado_libre_scraping(query: str):
    """
    Realiza scraping de la web de Mercado Libre México para precios.
    Devuelve precios ya convertidos a USD.
    """
    slug = query.replace(" ", "-")
    url = f"https://listado.mercadolibre.com.mx/{slug}" 
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", # User-Agent actualizado
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
        
        # --- SELECTORES MÁS ROBUSTOS / ALTERNATIVOS ---
        # AQUI ES DONDE PUEDES NECESITAR AÑADIR/AJUSTAR SELECTORES BASADOS EN TU INSPECCIÓN
        price_selectors = [
            "span.andes-money-amount__fraction", 
            "div.ui-search-price__second-line span.andes-money-amount__fraction",
            "span.andes-money-amount__parts:first-child .andes-money-amount__fraction",
            "span[data-testid='price-part']",
            ".ui-search-item__group__element--price span.andes-money-amount__fraction",
            ".ui-search-price__group .andes-money-amount__fraction", # Visto en algunos paises
            ".price-tag-fraction", # Selector antiguo
            ".andes-money-amount__container .andes-money-amount__fraction", # Otro posible contenedor
        ]
        
        price_tags = []
        for selector in price_selectors:
            found_tags = soup.select(selector)
            if found_tags:
                st.write(f"✔️ Selector `{selector}` encontró {len(found_tags)} elementos.")
                price_tags.extend(found_tags)
                # Opcional: break aquí si quieres capturar solo los primeros que funcionen
                # break
            else:
                st.write(f"❌ Selector `{selector}` no encontró elementos.")
        
        if not price_tags:
            st.info("Scraping: Ninguno de los selectores directos encontró elementos de precio. Intentando fallback con Regex...")
            # Fallback con expresiones regulares para buscar patrones de precios
            # Este regex busca '$' seguido de dígitos, puntos y comas.
            price_matches = re.findall(r'\$\s*(\d{1,3}(?:[\.,]\d{3})*(?:,\d{2})?)', resp.text)
            st.write(f"Fallback Regex encontró {len(price_matches)} coincidencias.")
            for match in price_matches:
                clean_price = match.replace('.', '').replace(',', '').strip() 
                try:
                    val_mxn = float(clean_price)
                    if 50 < val_mxn < 5000000: # Rango amplio para MXN
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
                if 50 < val_mxn < 5000000: # Rango amplio para MXN
                    precios_usd.append(convertir_a_usd(val_mxn, "MXN"))
            except ValueError:
                continue
        st.write(f"Scraping finalizó. Encontrados {len(precios_usd)} precios válidos.")

    except requests.exceptions.Timeout:
        st.warning("⚠️ Scraping: Tiempo de espera agotado al intentar acceder a Mercado Libre.")
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Scraping: Error de red o HTTP al intentar acceder a Mercado Libre: {e}. URL: {url}")
        if "403 Client Error: Forbidden" in str(e):
            st.warning("Mercado Libre podría haber bloqueado la petición. Intenta cambiar el User-Agent o usar un proxy/VPN.")
        elif "404 Client Error" in str(e):
            st.warning(f"La URL de scraping (`{url}`) no se encontró en Mercado Libre México. Revisa tu query.")
    except Exception as e:
        st.error(f"⚠️ Scraping: Error inesperado durante el proceso: {e}")

    return precios_usd


def calcular_valor_empeno(precios_usd: list, antiguedad: int, condicion: int):
    """
    Calcula el valor de empeño base ajustado por antigüedad y condición.
    Todos los precios deben estar ya en USD.
    """
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
    """
    Genera un comentario de IA con una recomendación de valor de empeño.
    Requiere una API key de OpenAI.
    """
    if not client:
        return "⚠️ IA no disponible: No se encontró la API key de OpenAI. Por favor, configúrala en el archivo '.env'."

    prompt = f"""
Eres un tasador experto de casas de empeño en Latinoamérica, conocido por tus recomendaciones realistas y equilibradas.

Artículo a evaluar:
- Búsqueda principal: "{query}"
- Descripción del usuario: "{descripcion}"
- Precio original (nuevo): {precio_original:.2f} USD
- Antigüedad: {antiguedad} años
- Condición (1-10): {condicion}/10

Datos de mercado (ya en USD):
- Mediana: {stats['mediana']:.2f} USD
- Promedio: {stats['promedio']:.2f} USD
- Rango de mercado: {stats['minimo']:.2f} - {stats['maximo']:.2f} USD

Factores aplicados por el sistema:
- Por antigüedad ({antiguedad} años): {stats['factor_antiguedad']:.2f}
- Por condición ({condicion}/10): {stats['factor_condicion']:.2f}
- Factor de riesgo y ganancia de empeño: {stats['factor_riesgo_ganancia']:.2f}

Valor base estimado por el sistema (antes de tu IA): {stats['valor_base']:.2f} USD.

Tu tarea:
Basándote en toda la información, propón un valor de empeño final que sea realista y atractivo para el cliente,
y justifica tu recomendación en **máximo 20 palabras**. Ajusta el valor base del sistema si lo consideras apropiado.
Recuerda que los clientes buscan el mejor trato posible, pero la casa de empeño debe ser rentable.

Formato EXACTO de respuesta (importante para el procesamiento):
VALOR_RECOMENDADO_FINAL: <número en USD> - <tu justificación concisa>.
"""

    try:
        with st.spinner("La IA está evaluando el artículo..."):
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "Eres un tasador de empeño que equilibra la oferta justa con la rentabilidad.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
                max_tokens=100
            )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Error consultando la IA: {e}. Asegúrate de que tu API Key sea válida y tengas créditos."

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