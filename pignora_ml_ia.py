def construir_query(categoria: str, modelo: str) -> str:
    """
    Crea una query más inteligente combinando categoría y modelo.
    Si no hay coincidencia, invierte el orden para maximizar coincidencias en buscadores.
    """
    if not modelo:
        return categoria.strip()
    if categoria.lower() in modelo.lower():
        return modelo.strip()
    return f"{modelo} {categoria}".strip()


# ================== eBAY SCRAPER ==================
def buscar_ebay_publico(query: str):
    slug = query.replace(" ", "+")
    url = f"https://www.ebay.com/sch/i.html?_nkw={slug}&_sop=12"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []

    st.write(f"🔹 eBay: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            st.warning(f"⚠️ eBay devolvió código {resp.status_code}")
            return [], []
        matches = re.findall(r'\$\d+(?:\.\d{2})?', resp.text)
        for m in matches:
            val = float(m.replace("$", ""))
            if 20 < val < 10000:
                precios.append(val)
        for p in precios[:10]:
            resultados.append({"Fuente": "eBay", "Título": query, "Precio USD": p, "Link": url})
        if not precios:
            st.info("Sin coincidencias visibles en eBay.")
        return precios, resultados
    except Exception as e:
        st.warning(f"⚠️ eBay no disponible: {e}")
        return [], []


# ================== GOOGLE SHOPPING ==================
def buscar_google_shopping(query: str):
    """
    Extrae precios de Google Shopping (SERPs públicas).
    Usa selectores HTML y fallback regex para mejorar precisión.
    """
    slug = query.replace(" ", "+")
    url = f"https://www.google.com/search?tbm=shop&q={slug}"
    headers = {"User-Agent": "Mozilla/5.0"}
    precios, resultados = [], []

    st.write(f"🔹 Google Shopping: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 1️⃣ Detectar precios usando patrones comunes de los resultados
        price_spans = soup.select("span[aria-hidden='true']") + soup.select("span:contains('$')")
        for span in price_spans:
            txt = span.get_text(strip=True)
            if re.match(r"\$?\d{2,4}(\.\d{1,2})?", txt):
                val = float(txt.replace("$", "").replace(",", ""))
                if 10 < val < 10000:
                    precios.append(val)

        # 2️⃣ Fallback: buscar con regex global si lo anterior no encontró nada
        if not precios:
            fallback = re.findall(r"\$\s?\d+(?:\.\d{2})?", soup.get_text())
            for t in fallback:
                val = float(t.replace("$", "").replace(",", ""))
                if 10 < val < 10000:
                    precios.append(val)

        # 3️⃣ Construir resultados
        for p in precios[:10]:
            resultados.append({"Fuente": "Google Shopping", "Título": query, "Precio USD": p, "Link": url})

        if not precios:
            st.info("Sin precios detectados en Google Shopping (HTML cambió o sin coincidencias).")
        return precios, resultados

    except Exception as e:
        st.warning(f"⚠️ Google Shopping no disponible: {e}")
        return [], []


# ================== ENCUENTRA24 (RSS FEED) ==================
def buscar_encuentra24(query: str):
    """
    Busca precios en el feed RSS de Encuentra24 (clasificados).
    Aplica filtrado por palabra clave en título o descripción.
    """
    url = "https://www.encuentra24.com/panama-es/clasificados?feed=rss"
    precios, resultados = [], []

    st.write(f"🔹 Encuentra24: {url}")
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            st.info("⚠️ No se pudieron leer entradas RSS (posible bloqueo temporal).")
            return [], []

        query_lower = query.lower()
        for entry in feed.entries[:50]:
            title = entry.get("title", "").lower()
            summary = entry.get("summary", "").lower()
            if query_lower in title or query_lower in summary:
                # Buscar precios tanto en el título como en el resumen
                text_to_scan = f"{entry.title} {entry.get('summary', '')}"
                matches = re.findall(r"\$\s?(\d+(?:\.\d{2})?)", text_to_scan)
                for m in matches:
                    val = float(m)
                    if 20 < val < 10000:
                        precios.append(val)
                        resultados.append({
                            "Fuente": "Encuentra24",
                            "Título": entry.title[:60] + "...",
                            "Precio USD": val,
                            "Link": entry.link,
                        })

        if not precios:
            st.info("Sin coincidencias de precios o palabras clave en Encuentra24.")
        return precios, resultados

    except Exception as e:
        st.warning(f"⚠️ Encuentra24 no disponible: {e}")
        return [], []
