import os
import re
import json
import urllib.parse
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import urllib.request

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ==================== SAYFA AYARLARI ====================
st.set_page_config(
    page_title="2-C Bütüncül Gelişim & DOKS Analitik Paneli",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== YAPILANDIRMA & VERİ ÇEKME ====================
DEFAULT_SHEET_ID = "173-bZAG4XovDG8ZJlXj3CrgV5D7VAAZk83FxLFT0Tj8"

def get_secret(key, default=""):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)

SHEET_ID = get_secret("SHEET_ID", DEFAULT_SHEET_ID)
OPENAI_API_KEY = get_secret("OPENAI_API_KEY", "")


def gsheet_export_csv_url(sheet_id, sheet_name):
    # gviz yerine doğrudan Google Sheets CSV export uç noktası kullanılır;
    # böylece hem saf sayı ('116') hem metin ('90 (%100)') içeren hücreler asla boş dönmez.
    encoded_name = urllib.parse.quote(sheet_name)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_name}&headers=0"


@st.cache_data(ttl=30)
def gsheet_json_satirlari_getir(sheet_id, sheet_name):
    encoded_name = urllib.parse.quote(sheet_name)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:json&sheet={encoded_name}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        ham_metin = resp.read().decode("utf-8")

    veri = json.loads(ham_metin[ham_metin.find("{"):ham_metin.rfind("}") + 1])
    satirlar = []
    for row in veri.get("table", {}).get("rows", []):
        satir = []
        for cell in (row.get("c") or []):
            if cell is None:
                satir.append("")
            elif cell.get("f") is not None:
                satir.append(str(cell["f"]).strip())
            elif cell.get("v") is not None:
                satir.append(str(cell["v"]).strip())
            else:
                satir.append("")
        satirlar.append(satir)
    return satirlar

# ==================== DOKS & DOĞRULUK AYIKLAMA MOTORU ====================
def doks_verisi_ayikla(not_degeri):
    """
    Hem eski ('65 kelime', 'DOKS: 72 (%95)') hem yeni ('90 (%100)', '85 (%96)', '90')
    formatlarını tip güvenli şekilde ayıklar.
    """
    if pd.isna(not_degeri):
        return None, None
    metin = str(not_degeri).strip()
    if not metin:
        return None, None

    # 1. Doğruluk yüzdesini ayıkla: örn. (%100), %95, (%98.5)
    yuzde = None
    yuzde_eslesme = re.search(r'%\s*(\d+(?:[.,]\d+)?)', metin)
    if yuzde_eslesme:
        try:
            yuzde = float(yuzde_eslesme.group(1).replace(',', '.'))
        except ValueError:
            yuzde = None
        metin_temiz = re.sub(r'\(?\s*%\s*\d+(?:[.,]\d+)?\s*\)?', '', metin).strip()
    else:
        metin_temiz = metin

    # 2. DOKS (kelime sayısı) ayıkla
    etiketli = re.search(
        r'(?:DOKS\s*[:=-]?\s*(\d+))|(\d+)\s*(?:kelime|dk|dakika)',
        metin_temiz,
        re.IGNORECASE
    )
    if etiketli:
        return int(etiketli.group(1) or etiketli.group(2)), yuzde

    baslangic_sayi = re.match(r'^(\d{1,3})\b', metin_temiz)
    if baslangic_sayi:
        val = int(baslangic_sayi.group(1))
        if 5 <= val <= 300:
            return val, yuzde

    genel_sayi = re.search(r'\b(\d{1,3})\b', metin_temiz)
    if genel_sayi:
        val = int(genel_sayi.group(1))
        if 5 <= val <= 300:
            return val, yuzde

    return None, yuzde


def doks_verilerini_hazirla(df_kayit, ogrenci_listesi):
    ozet_kolonlar = [
        "Öğrenci", "İlk DOKS", "Son DOKS", "Fark",
        "Ölçüm Sayısı", "Son Doğruluk (%)", "Durum"
    ]
    if df_kayit is None or df_kayit.empty:
        return pd.DataFrame(), pd.DataFrame(columns=ozet_kolonlar)

    df = df_kayit.copy()
    hedef_str = df["Hedef"].fillna("").astype(str)
    not_str = df["Not"].fillna("").astype(str)

    # Okuma akıcılığı satırlarını belirle (SRSD ve Günlük Ödev etiketlerini hariç tut)
    maske = (
        hedef_str.str.contains("akıcı|okuma|DOKS|kelime", case=False, regex=True) |
        not_str.str.contains(r"DOKS|kelime|^\d{1,3}\s*\(%?\d+", case=False, regex=True)
    ) & (~not_str.str.contains(r"\[SRSD|\[Günlük Ödev\]", case=False, regex=True))

    df_okuma = df[maske].copy()
    if df_okuma.empty:
        return pd.DataFrame(), pd.DataFrame(columns=ozet_kolonlar)

    ayiklanan = df_okuma["Not"].apply(doks_verisi_ayikla)
    df_okuma["DOKS"] = [x[0] for x in ayiklanan]
    df_okuma["Dogruluk"] = [x[1] for x in ayiklanan]

    df_okuma["DOKS"] = pd.to_numeric(df_okuma["DOKS"], errors="coerce")
    df_okuma = df_okuma.dropna(subset=["DOKS"]).copy()
    if df_okuma.empty:
        return pd.DataFrame(), pd.DataFrame(columns=ozet_kolonlar)

    df_okuma["DOKS"] = df_okuma["DOKS"].astype(int)
    df_okuma["Dogruluk"] = pd.to_numeric(df_okuma["Dogruluk"], errors="coerce")

    # Kronolojik sıralama (Aynı gün girilen kayıtlarda tablo sırasını koru)
    df_okuma["_satir_no"] = range(len(df_okuma))
    df_okuma = df_okuma.sort_values(["Tarih_DT", "_satir_no"], na_position="last").reset_index(drop=True)
    df_okuma["Ölçüm Sırası"] = df_okuma.groupby("Ogrenci").cumcount() + 1
    df_okuma["Ölçüm Etiketi"] = df_okuma["Ölçüm Sırası"].astype(str) + ". Ölçüm"

    # 28 öğrencinin tamamı için özet tablo
    ozet_satirlar = []
    for ogr in ogrenci_listesi:
        ogr_df = df_okuma[df_okuma["Ogrenci"].str.strip() == str(ogr).strip()]
        if not ogr_df.empty:
            ilk_doks = int(ogr_df["DOKS"].iloc[0])
            son_doks = int(ogr_df["DOKS"].iloc[-1])
            fark = int(son_doks - ilk_doks)
            olcum_sayisi = int(len(ogr_df))
            dog_seri = ogr_df["Dogruluk"].dropna()
            son_dog = float(dog_seri.iloc[-1]) if not dog_seri.empty else None

            if olcum_sayisi == 1:
                durum = "Tek Ölçüm"
            elif fark > 0:
                durum = f"+{fark} Kelime Artış"
            elif fark < 0:
                durum = f"{fark} Kelime Düşüş"
            else:
                durum = "Sabit"

            ozet_satirlar.append({
                "Öğrenci": ogr,
                "İlk DOKS": ilk_doks,
                "Son DOKS": son_doks,
                "Fark": fark,
                "Ölçüm Sayısı": olcum_sayisi,
                "Son Doğruluk (%)": son_dog,
                "Durum": durum
            })
        else:
            ozet_satirlar.append({
                "Öğrenci": ogr,
                "İlk DOKS": None,
                "Son DOKS": None,
                "Fark": None,
                "Ölçüm Sayısı": 0,
                "Son Doğruluk (%)": None,
                "Durum": "Ölçüm Yok"
            })

    df_doks_ozet = pd.DataFrame(ozet_satirlar, columns=ozet_kolonlar)
    return df_okuma, df_doks_ozet


# ==================== OPENAI PEDAGOJİK RAPOR ÜRETİCİ ====================
def openai_pedagojik_yorum_uret(ogrenci_adi, kayit_ozeti_metni):
    if not OPENAI_API_KEY:
        return "⚠️ Streamlit Secrets veya ortam değişkenlerinde `OPENAI_API_KEY` tanımlı değil."
    if OpenAI is None:
        return "⚠️ `openai` kütüphanesi yüklü değil. `requirements.txt` dosyasına `openai` ekleyin."

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""
Sen Türkiye Yüzyılı Maarif Modeli (TYMM) ve 2. sınıf biçimlendirici değerlendirme süreçlerinde uzman bir ilkokul öğretmenisin.
Aşağıda 2-C sınıfı öğrencisi **{ogrenci_adi}** için toplanan gözlem, çalışma kâğıdı, SRSD yazma, günlük ödev ve DOKS (okuma akıcılığı) verileri yer almaktadır:

{kayit_ozeti_metni}

Lütfen bu verilere dayanarak:
1. **Güçlü Yönler:** Öğrencinin öne çıkan akademik, yazma (SRSD) ve okuma akıcılığı becerilerini somut verilerle özetle.
2. **Geliştirilmesi Gereken Alanlar:** Desteklenmesi gereken kazanımları veya okuma/yazma boyutlarını yapıcı bir dille belirt.
3. **Öğretmen & Veli İçin Eylem Önerisi:** Evde ve sınıfta uygulanabilecek 2-3 kısa, somut etkinlik önerisi yaz.
4. **e-Okul Gelişim Raporu Taslağı:** Dönem sonu öğrenci gelişim raporuna doğrudan yapıştırılabilecek 3-4 cümlelik resmi, sıcak ve pedagojik bir değerlendirme paragrafı oluştur.
"""
    for model_adi in ["gpt-4o-mini", "gpt-4o"]:
        try:
            resp = client.chat.completions.create(
                model=model_adi,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": "Türkiye Yüzyılı Maarif Modeli (TYMM) uzmanı ilkokul öğretmeni asistanı."},
                    {"role": "user", "content": prompt}
                ]
            )
            return resp.choices[0].message.content
        except Exception as e:
            son_hata = str(e)
    return f"OpenAI API Hatası: {son_hata}"


# ==================== VERİLERİ YÜKLE ====================
ogrenci_listesi, df_kayit, df_hedef = verileri_yukle(SHEET_ID)
df_okuma, df_doks_ozet = doks_verilerini_hazirla(df_kayit, ogrenci_listesi)

# ==================== ÜST BAŞLIK & KENAR ÇUBUĞU ====================
st.title("📊 2-C Sınıfı Bütüncül Gelişim & DOKS Analitik Paneli")
st.caption("Türkiye Yüzyılı Maarif Modeli (TYMM) Süreç Odaklı İzleme, SRSD Yazma & Okuma Akıcılığı Analizi")

with st.sidebar:
    st.header("⚙️ Filtre ve Kontroller")
    if st.button("🔄 Verileri Şimdi Yenile", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.metric("Kayıtlı Öğrenci", f"{len(ogrenci_listesi)} Öğrenci")
    st.metric("Toplam Gözlem / Ölçüm", f"{len(df_kayit)} Kayıt")

    secili_ogrenci = st.selectbox(
        "👤 Bireysel Öğrenci İncelemesi",
        options=["Tüm Sınıf"] + ogrenci_listesi
    )

    alan_secenekleri = ["Tümü"] + sorted([a for a in df_kayit["Alan"].unique() if a])
    secili_alan = st.selectbox("📂 Gelişim Alanı Filtresi", options=alan_secenekleri)

# Filtrelenmiş kayıtlar
df_filtre = df_kayit.copy()
if secili_ogrenci != "Tüm Sınıf":
    df_filtre = df_filtre[df_filtre["Ogrenci"] == secili_ogrenci]
if secili_alan != "Tümü":
    df_filtre = df_filtre[df_filtre["Alan"] == secili_alan]

# ==================== ANA SEKMELER ====================
tab_doks, tab_genel, tab_srsd, tab_ai = st.tabs([
    "📖 Okuma Akıcılığı (DOKS)",
    "🎯 Kazanım & Süreç Analizi",
    "✍️ SRSD Yazma & Günlük Ödev",
    "🤖 AI Gelişim Raporu (OpenAI)"
])

# -------------------- 1. SEKME: DOKS OKUMA AKICILIĞI --------------------
with tab_doks:
    st.subheader("📖 Sınıf Geneli ve Bireysel DOKS (Dakikada Okunan Kelime Sayısı) Analizi")

    olculen_df = df_doks_ozet.dropna(subset=["Son DOKS"]).copy()

    if olculen_df.empty:
        st.info("Henüz DOKS (okuma akıcılığı) kaydı bulunamadı.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        ort_son = olculen_df["Son DOKS"].mean()
        cift_olcum = olculen_df[olculen_df["Ölçüm Sayısı"] >= 2]
        ort_fark = cift_olcum["Fark"].mean() if not cift_olcum.empty else 0.0
        en_yuksek = olculen_df["Son DOKS"].max()
        ort_dog = olculen_df["Son Doğruluk (%)"].dropna().mean()

        col1.metric("Sınıf Son DOKS Ortalaması", f"{ort_son:.1f} kelime/dk")
        col2.metric("Ortalama Gelişim İvmesi", f"{ort_fark:+.1f} kelime", delta=f"{len(cift_olcum)} öğrencide 2+ ölçüm")
        col3.metric("En Yüksek Okuma Hızı", f"{int(en_yuksek)} kelime/dk")
        col4.metric("Ortalama Okuma Doğruluğu", f"%{ort_dog:.1f}" if pd.notna(ort_dog) else "-")

        st.markdown("---")

        # 1. Grafik: Sınıf Geneli DOKS Isı Haritası (Tüm 28 Öğrenci x Ölçümler)
        st.markdown("### 🌡️ Sınıf Geneli DOKS Gelişim Isı Haritası (28 Öğrenci)")
        if not df_okuma.empty:
            pivot_doks = df_okuma.pivot_table(
                index="Ogrenci",
                columns="Ölçüm Etiketi",
                values="DOKS",
                aggfunc="last"
            ).reindex(ogrenci_listesi)

            # Ölçüm sütunlarını sayısal sıraya göre diz
            sirali_kolonlar = sorted(
                pivot_doks.columns,
                key=lambda x: int(re.search(r'(\d+)', str(x)).group(1)) if re.search(r'(\d+)', str(x)) else 0
            )
            pivot_doks = pivot_doks[sirali_kolonlar]

            fig_heat = px.imshow(
                pivot_doks,
                text_auto=True,
                aspect="auto",
                color_continuous_scale="YlGnBu",
                labels=dict(x="Ölçüm Sırası", y="Öğrenci", color="DOKS (Kelime/Dk)")
            )
            fig_heat.update_layout(height=max(560, len(ogrenci_listesi) * 23), margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig_heat, use_container_width=True)

        # 2. Grafik: İlk ve Son Ölçüm Karşılaştırma Grafiği
        st.markdown("### 📈 İlk Ölçüm ve Son Ölçüm Karşılaştırması")
        karsilastirma_df = olculen_df.sort_values("Son DOKS", ascending=True)
        fig_comp = go.Figure()
        fig_comp.add_trace(go.Bar(
            y=karsilastirma_df["Öğrenci"],
            x=karsilastirma_df["İlk DOKS"],
            name="İlk Ölçüm",
            orientation="h",
            marker_color="#94a3b8"
        ))
        fig_comp.add_trace(go.Bar(
            y=karsilastirma_df["Öğrenci"],
            x=karsilastirma_df["Son DOKS"],
            name="Son Ölçüm",
            orientation="h",
            marker_color="#2563eb"
        ))
        fig_comp.update_layout(
            barmode="group",
            height=max(560, len(karsilastirma_df) * 25),
            xaxis_title="Dakikada Okunan Doğru Kelime Sayısı (DOKS)",
            yaxis_title="",
            margin=dict(l=10, r=10, t=20, b=10)
        )
        st.plotly_chart(fig_comp, use_container_width=True)

        # 3. Bireysel Gelişim Eğrisi (Öğrenci seçildiyse)
        if secili_ogrenci != "Tüm Sınıf":
            st.markdown(f"### 👤 {secili_ogrenci} — Bireysel Okuma Hızı ve Doğruluk Eğrisi")
            ogr_okuma = df_okuma[df_okuma["Ogrenci"] == secili_ogrenci].copy()
            if not ogr_okuma.empty:
                fig_line = px.line(
                    ogr_okuma,
                    x="Ölçüm Etiketi",
                    y="DOKS",
                    markers=True,
                    text="DOKS",
                    title=f"{secili_ogrenci} DOKS Seyri"
                )
                fig_line.update_traces(textposition="top center", line_width=3, marker_size=10)
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.warning(f"{secili_ogrenci} için henüz DOKS kaydı girilmemiş.")

        # 4. Tam Sınıf Özet Tablosu (28 Öğrenci)
        st.markdown("### 📋 Tüm Sınıf DOKS Özet Çizelgesi")
        st.dataframe(
            df_doks_ozet,
            use_container_width=True,
            hide_index=True,
            column_config={
                "İlk DOKS": st.column_config.NumberColumn("İlk DOKS", format="%d"),
                "Son DOKS": st.column_config.NumberColumn("Son DOKS", format="%d"),
                "Fark": st.column_config.NumberColumn("Gelişim Farkı", format="%+d"),
                "Son Doğruluk (%)": st.column_config.NumberColumn("Son Doğruluk (%)", format="%.1f%%")
            }
        )

# -------------------- 2. SEKME: KAZANIM & SÜREÇ ANALİZİ --------------------
with tab_genel:
    st.subheader("🎯 Öğrenme Çıktıları ve Dereceli Puanlama (1–4 Düzey) Dağılımı")

    puanli_df = df_filtre[df_filtre["Puan"] > 0].copy()
    if puanli_df.empty:
        st.info("Seçili filtreye uygun puanlanmış değerlendirme kaydı bulunamadı.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Ortalama Düzey Puanı", f"{puanli_df['Puan'].mean():.2f} / 4.00")
        c2.metric("4 (Çok İyi) Oranı", f"%{(puanli_df['Puan'] == 4).mean() * 100:.1f}")
        c3.metric("Destek Gerektiren (1-2 Düzey)", f"{(puanli_df['Puan'] <= 2).sum()} Kayıt")

        ders_ort = puanli_df.groupby("Ders", as_index=False)["Puan"].mean().sort_values("Puan", ascending=False)
        fig_ders = px.bar(
            ders_ort,
            x="Ders",
            y="Puan",
            color="Ders",
            text_auto=".2f",
            range_y=[0, 4.3],
            title="Derslere Göre Ortalama Performans Düzeyi"
        )
        st.plotly_chart(fig_ders, use_container_width=True)

        st.markdown("### 🗂️ Detaylı Gözlem ve Değerlendirme Kayıtları")
        gosterim_df = df_filtre[["Tarih", "Ogrenci", "Alan", "Ders", "Hedef", "Puan", "Not"]].sort_index(ascending=False)
        st.dataframe(gosterim_df, use_container_width=True, hide_index=True)

# -------------------- 3. SEKME: SRSD YAZMA & GÜNLÜK ÖDEV --------------------
with tab_srsd:
    st.subheader("✍️ SRSD 4 Boyutlu Yazma ve Günlük Ödev Kontrolleri")

    col_sol, col_sag = st.columns(2)

    with col_sol:
        st.markdown("#### ✍️ SRSD Yazma Analizleri")
        srsd_df = df_filtre[df_filtre["Not"].str.contains(r"\[SRSD", case=False, regex=True)].copy()
        if srsd_df.empty:
            st.info("Henüz SRSD yazma değerlendirmesi kaydı bulunmuyor.")
        else:
            srsd_df["Boyut"] = srsd_df["Not"].str.extract(r"\[SRSD\s*-\s*([^\]]+)\]", expand=False).fillna("Genel")
            boyut_ort = srsd_df[srsd_df["Puan"] > 0].groupby("Boyut", as_index=False)["Puan"].mean()
            if not boyut_ort.empty:
                fig_srsd = px.bar(
                    boyut_ort,
                    x="Boyut",
                    y="Puan",
                    color="Boyut",
                    text_auto=".2f",
                    range_y=[0, 4.3],
                    title="SRSD Boyutlarına Göre Ortalama Puan"
                )
                st.plotly_chart(fig_srsd, use_container_width=True)
            st.dataframe(srsd_df[["Tarih", "Ogrenci", "Boyut", "Puan", "Not"]].sort_index(ascending=False), use_container_width=True, hide_index=True)

    with col_sag:
        st.markdown("#### 📑 Günlük Ödev PDF Kontrolleri")
        odev_df = df_filtre[df_filtre["Not"].str.contains(r"\[Günlük Ödev\]", case=False, regex=True)].copy()
        if odev_df.empty:
            st.info("Henüz Günlük Ödev PDF değerlendirme kaydı bulunmuyor.")
        else:
            st.metric("Toplam Ödev Kaydı", f"{len(odev_df)} Kayıt")
            st.dataframe(odev_df[["Tarih", "Ogrenci", "Ders", "Hedef", "Puan", "Not"]].sort_index(ascending=False), use_container_width=True, hide_index=True)

# -------------------- 4. SEKME: AI PEDAGOJİK GELİŞİM RAPORU --------------------
with tab_ai:
    st.subheader("🤖 Yapay Zekâ Destekli Öğrenci Gelişim & e-Okul Raporu (OpenAI)")

    rapor_ogrenci = st.selectbox(
        "Rapor oluşturulacak öğrenciyi seçin:",
        options=ogrenci_listesi,
        index=ogrenci_listesi.index(secili_ogrenci) if secili_ogrenci in ogrenci_listesi else 0
    )

    if st.button("✨ Pedagojik Gelişim Raporu ve e-Okul Taslağı Üret", type="primary"):
        ogr_kayitlar = df_kayit[df_kayit["Ogrenci"] == rapor_ogrenci].copy()
        ogr_doks = df_doks_ozet[df_doks_ozet["Öğrenci"] == rapor_ogrenci]

        if ogr_kayitlar.empty and ogr_doks.empty:
            st.warning(f"{rapor_ogrenci} için henüz kayıt bulunamadı.")
        else:
            with st.spinner(f"{rapor_ogrenci} için tüm gözlem, SRSD ve DOKS verileri analiz ediliyor..."):
                ozet_satirlar = []
                if not ogr_doks.empty and pd.notna(ogr_doks["Son DOKS"].iloc[0]):
                    r = ogr_doks.iloc[0]
                    ozet_satirlar.append(
                        f"- Okuma Akıcılığı (DOKS): İlk ölçüm {int(r['İlk DOKS'])} kelime/dk, "
                        f"Son ölçüm {int(r['Son DOKS'])} kelime/dk (Fark: {int(r['Fark']):+d}), "
                        f"Son Doğruluk: %{r['Son Doğruluk (%)'] if pd.notna(r['Son Doğruluk (%)']) else '-'}"
                    )

                for _, row in ogr_kayitlar.tail(35).iterrows():
                    temiz_not = re.sub(r"https?://\S+", "[Drive Kanıtı]", str(row["Not"]))
                    ozet_satirlar.append(
                        f"- [{row['Tarih']}] {row['Ders']} | {row['Hedef']} | Puan: {int(row['Puan'])}/4 | Not: {temiz_not}"
                    )

                rapor_metni = openai_pedagojik_yorum_uret(rapor_ogrenci, "\n".join(ozet_satirlar))
                st.markdown(rapor_metni)
