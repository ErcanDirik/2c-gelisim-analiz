import re
import json
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from datetime import datetime

# ==================== SAYFA YAPILANDIRMASI ====================
st.set_page_config(
    page_title="2-C Bütüncül Gelişim & DOKS Analitik Paneli",
    page_icon="📊",
    layout="wide"
)

SHEET_ID = st.secrets.get("SHEET_ID", "173-bZAG4XovDG8ZJlXj3CrgV5D7VAAZk83FxLFT0Tj8")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# ==================== VERİ ÇEKME & ÖNBELLEK ====================
@st.cache_data(ttl=120)
def verileri_yukle():
    base_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet="
    
    df_kayit = pd.read_csv(base_url + "Kayitlar")
    df_ogr = pd.read_csv(base_url + "Ogrenciler")
    df_hedef = pd.read_csv(base_url + "Hedefler")

    df_kayit.columns = [c.strip() for c in df_kayit.columns]
    # Standart sütun isimlerine eşitle
    beklenen = ["Tarih", "Ogrenci", "Alan", "Ders", "Hedef", "Puan", "Not"]
    if len(df_kayit.columns) >= 7:
        df_kayit = df_kayit.iloc[:, :7]
        df_kayit.columns = beklenen

    df_kayit["Ogrenci"] = df_kayit["Ogrenci"].astype(str).str.strip()
    df_kayit["Alan"] = df_kayit["Alan"].astype(str).str.strip()
    df_kayit["Ders"] = df_kayit["Ders"].astype(str).str.strip()
    df_kayit["Hedef"] = df_kayit["Hedef"].astype(str).str.strip()
    df_kayit["Puan"] = pd.to_numeric(df_kayit["Puan"], errors="coerce")
    df_kayit["Not"] = df_kayit["Not"].fillna("").astype(str).str.strip()
    df_kayit = df_kayit.dropna(subset=["Ogrenci", "Puan"])
    df_kayit = df_kayit[df_kayit["Ogrenci"] != ""]

    ogrenci_listesi = (
        df_ogr.iloc[:, 0]
        .dropna()
        .astype(str)
        .str.strip()
        .tolist()
    )
    ogrenci_listesi = [
        o for o in ogrenci_listesi
        if o.lower() not in ["ogrenci", "öğrenci", "ad soyad", "nan", ""]
    ]

    return df_kayit, ogrenci_listesi, df_hedef

# ==================== DOKS & DOĞRULUK AYIKLAYICI ====================
def doks_verilerini_hazirla(df_kayit, ogrenci_listesi):
    maske = df_kayit["Hedef"].str.lower().str.contains("okuma|akıcı|akici", regex=True)
    df_okuma = df_kayit[maske].copy()

    def ayikla(not_str):
        s = str(not_str or "").strip()
        m_doks = re.search(r"(\d+)", s)
        m_yuzde = re.search(r"\(\s*%?\s*(\d+(?:[.,]\d+)?)\s*%?\s*\)", s) or re.search(r"%\s*(\d+(?:[.,]\d+)?)", s)
        doks = int(m_doks.group(1)) if m_doks else None
        yuzde = float(m_yuzde.group(1).replace(",", ".")) if m_yuzde else None
        return pd.Series([doks, yuzde])

    if not df_okuma.empty:
        df_okuma[["DOKS", "Dogruluk"]] = df_okuma["Not"].apply(ayikla)
        df_okuma = df_okuma.dropna(subset=["DOKS"])
        df_okuma["DOKS"] = df_okuma["DOKS"].astype(int)
        df_okuma["OlcumNo"] = df_okuma.groupby("Ogrenci").cumcount() + 1
    else:
        df_okuma["DOKS"] = pd.Series(dtype="int")
        df_okuma["Dogruluk"] = pd.Series(dtype="float")
        df_okuma["OlcumNo"] = pd.Series(dtype="int")

    # Öğrenci bazlı özet tablosu (İlk, Son, Fark, Ortalama Doğruluk)
    ozet_satirlar = []
    for ogr in ogrenci_listesi:
        sub = df_okuma[df_okuma["Ogrenci"] == ogr]
        if sub.empty:
            ozet_satirlar.append({
                "Öğrenci": ogr,
                "Ölçüm Sayısı": 0,
                "İlk DOKS": None,
                "Son DOKS": None,
                "Değişim (Kelime)": None,
                "Son Doğruluk (%)": None
            })
        else:
            ilk = int(sub.iloc[0]["DOKS"])
            son = int(sub.iloc[-1]["DOKS"])
            son_dog = sub.iloc[-1]["Dogruluk"]
            ozet_satirlar.append({
                "Öğrenci": ogr,
                "Ölçüm Sayısı": len(sub),
                "İlk DOKS": ilk,
                "Son DOKS": son,
                "Değişim (Kelime)": son - ilk,
                "Son Doğruluk (%)": round(son_dog, 1) if pd.notna(son_dog) else None
            })

    df_ozet = pd.DataFrame(ozet_satirlar)
    return df_okuma, df_ozet

# ==================== HIZLANDIRILMIŞ FLASH-LITE GEMINI YÖNETİCİSİ ====================
@st.cache_data(ttl=21600)
def aktif_lite_modelleri_getir(api_key):
    oncelikli = [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite-preview",
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite-preview"
    ]
    if not api_key:
        return oncelikli
    try:
        resp = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
            timeout=6
        )
        data = resp.json()
        for m in data.get("models", []):
            ad = m.get("name", "").replace("models/", "")
            if "generateContent" in m.get("supportedGenerationMethods", []) and "flash-lite" in ad:
                if ad not in oncelikli:
                    oncelikli.append(ad)
    except Exception:
        pass
    return oncelikli

def gemini_karne_yorumu_uret(ogrenci, ogrenci_df, doks_ozet_satir):
    if not GEMINI_API_KEY:
        return "⚠️ GEMINI_API_KEY tanımlı değil. Streamlit Secrets ayarlarını kontrol edin."

    ozet_maddeler = []
    for (ders, hedef), grp in ogrenci_df.groupby(["Ders", "Hedef"]):
        ort = grp["Puan"].mean()
        ozet_maddeler.append(f"- [{ders}] {hedef}: {ort:.1f}/4")

    doks_notu = ""
    if doks_ozet_satir is not None and pd.notna(doks_ozet_satir["Son DOKS"]):
        ilk_d = int(doks_ozet_satir["İlk DOKS"])
        son_d = int(doks_ozet_satir["Son DOKS"])
        fark_d = int(doks_ozet_satir["Değişim (Kelime)"])
        dog_str = f", %{doks_ozet_satir['Son Doğruluk (%)']} doğruluk" if pd.notna(doks_ozet_satir["Son Doğruluk (%)"]) else ""
        doks_notu = f"\nOkuma Hızı Verisi: İlk ölçüm {ilk_d} kelime/dk -> Son ölçüm {son_d} kelime/dk (Değişim: {fark_d:+d} kelime{dog_str})."

    prompt = (
        f"Sen Türkiye Yüzyılı Maarif Modeli'ne (TYMM) hakim deneyimli bir 2. sınıf öğretmenisin.\n"
        f"Öğrenci: {ogrenci}\n"
        f"Gözlem ve Değerlendirme Ortalamaları (1-4 ölçeği):\n"
        + "\n".join(ozet_maddeler[:25])
        + doks_notu
        + "\n\nBu verilere dayanarak veli ve e-Okul gelişim raporu için 4-5 cümlelik, yapıcı, somut kanıtlara dayalı, "
        "akıcı ve profesyonel bir Türkçe değerlendirme paragrafı yaz. Sadece paragraf metnini döndür."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }

    modeller = aktif_lite_modelleri_getir(GEMINI_API_KEY)
    son_hata = ""

    for model_adi in modeller:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_adi}:generateContent?key={GEMINI_API_KEY}"
        for _ in range(2):
            try:
                r = requests.post(url, json=payload, timeout=15)
                res = r.json()
                if "candidates" in res and res["candidates"]:
                    return res["candidates"][0]["content"]["parts"][0]["text"].strip()
                son_hata = res.get("error", {}).get("message", f"HTTP {r.status_code}")
                if "thinking" in son_hata.lower():
                    payload["generationConfig"].pop("thinkingConfig", None)
                    continue
            except Exception as e:
                son_hata = str(e)
    return f"⚠️ AI Yorumu Üretilemedi: {son_hata}"

# ==================== ARAYÜZ BAŞLIĞI & VERİ YÜKLEME ====================
st.title("📊 2-C Sınıfı Bütüncül Gelişim & DOKS Analitik Paneli")

col_ust1, col_ust2 = st.columns([4, 1])
with col_ust1:
    st.caption("Türkiye Yüzyılı Maarif Modeli (TYMM) • Canlı Google Sheets Veritabanı • Flash-Lite AI Motoru")
with col_ust2:
    if st.button("🔄 Verileri Yenile", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

df_kayit, ogrenci_listesi, df_hedef = verileri_yukle()
df_okuma, df_doks_ozet = doks_verilerini_hazirla(df_kayit, ogrenci_listesi)

# ==================== ANA SEKMELER ====================
tab_genel, tab_doks, tab_ogrenci = st.tabs([
    "🏫 Sınıf Genel Durumu",
    "📖 DOKS (Okuma Hızı & Değişim)",
    "👤 Öğrenci Profili & AI Karne"
])

# -------------------- 1. SEKME: SINIF GENEL DURUMU --------------------
with tab_genel:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Gözlem Kaydı", len(df_kayit))
    c2.metric("Değerlendirilen Öğrenci", f"{df_kayit['Ogrenci'].nunique()} / {len(ogrenci_listesi)}")
    c3.metric("Sınıf Genel Ortalaması", f"{df_kayit['Puan'].mean():.2f} / 4.00")
    c4.metric("Farklı Öğrenme Çıktısı", df_kayit["Hedef"].nunique())

    st.divider()
    col_g1, col_g2 = st.columns(2)

    with col_g1:
        st.subheader("Gelişim Alanlarına Göre Sınıf Ortalaması")
        alan_ort = df_kayit.groupby("Alan")["Puan"].mean().sort_values(ascending=True)
        fig, ax = plt.subplots(figsize=(6, 3.2))
        renkler = ["#27ae60" if v >= 3.5 else "#3498db" if v >= 2.5 else "#f39c12" for v in alan_ort.values]
        bars = ax.barh(alan_ort.index, alan_ort.values, color=renkler, height=0.5)
        ax.set_xlim(0, 4.4)
        ax.axvline(3.0, color="#95a5a6", linestyle="--", linewidth=0.9)
        for bar in bars:
            w = bar.get_width()
            ax.text(w + 0.08, bar.get_y() + bar.get_height() / 2, f"{w:.2f}", va="center", fontweight="bold")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        st.pyplot(fig)

    with col_g2:
        st.subheader("Ders Bazlı Ortalama Puanlar")
        ders_ort = df_kayit.groupby("Ders")["Puan"].mean().sort_values(ascending=True)
        fig2, ax2 = plt.subplots(figsize=(6, 3.2))
        bars2 = ax2.barh(ders_ort.index, ders_ort.values, color="#2980b9", height=0.55)
        ax2.set_xlim(0, 4.4)
        for bar in bars2:
            w = bar.get_width()
            ax2.text(w + 0.08, bar.get_y() + bar.get_height() / 2, f"{w:.2f}", va="center", fontweight="bold")
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(False)
        st.pyplot(fig2)

# -------------------- 2. SEKME: DOKS (OKUMA HIZI & SINIF DEĞİŞİM HARİTASI) --------------------
with tab_doks:
    st.subheader("📖 Dakikada Okunan Kelime Sayısı (DOKS) & Sınıf Değişim Haritası")

    if df_okuma.empty:
        st.info("Henüz okuma hızı (DOKS) içeren bir kayıt bulunamadı. Not alanına '68 (%95)' formatında giriş yaptığınızda veriler burada otomatik görünür.")
    else:
        olculen_df = df_doks_ozet.dropna(subset=["Son DOKS"])
        ilk_sinif_ort = olculen_df["İlk DOKS"].mean()
        son_sinif_ort = olculen_df["Son DOKS"].mean()
        ort_artis = son_sinif_ort - ilk_sinif_ort
        dog_ort = olculen_df["Son Doğruluk (%)"].dropna().mean()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("İlk Ölçüm Sınıf Ortalaması", f"{ilk_sinif_ort:.1f} kelime/dk")
        m2.metric(
            "Son Ölçüm Sınıf Ortalaması",
            f"{son_sinif_ort:.1f} kelime/dk",
            delta=f"{ort_artis:+.1f} kelime/dk"
        )
        m3.metric("Ortalama Okuma Doğruluğu", f"%{dog_ort:.1f}" if pd.notna(dog_ort) else "-")
        m4.metric("Ölçülen Öğrenci Sayısı", f"{len(olculen_df)} / {len(ogrenci_listesi)}")

        st.divider()

        # 1) SINIF GENELİ DEĞİŞİM HARİTASI (ISI HARİTASI / HEATMAP)
        st.markdown("### 🗺️ Sınıf Geneli DOKS Değişim Haritası (Ölçüm Bazlı Isı Haritası)")
        st.caption("Her satır bir öğrenciyi, sütunlar sırasıyla yapılan okuma hızı ölçümlerini gösterir. Renk koyulaştıkça okuma hızı artar.")

        pivot_doks = df_okuma.pivot_table(
            index="Ogrenci",
            columns="OlcumNo",
            values="DOKS",
            aggfunc="last"
        )
        # Sınıf listesi sırasını koru
        sirali_ogr = [o for o in ogrenci_listesi if o in pivot_doks.index]
        pivot_doks = pivot_doks.loc[sirali_ogr]
        pivot_doks.columns = [f"{c}. Ölçüm" for c in pivot_doks.columns]

        # Son sütuna net değişim (+Δ) ekle
        degisim_harita_df = pivot_doks.copy()
        degisim_harita_df["Net Değişim"] = olculen_df.set_index("Öğrenci").loc[sirali_ogr, "Değişim (Kelime)"]

        fig_hm, ax_hm = plt.subplots(figsize=(11, max(6.5, len(sirali_ogr) * 0.32)))
        olcum_matrisi = pivot_doks.values.astype(float)

        cmap = plt.cm.YlGnBu
        cmap.set_bad(color="#f1f5f9")
        im = ax_hm.imshow(olcum_matrisi, cmap=cmap, aspect="auto", vmin=20, vmax=max(95, olculen_df["Son DOKS"].max()))

        ax_hm.set_xticks(range(len(pivot_doks.columns)))
        ax_hm.set_xticklabels(pivot_doks.columns, fontweight="bold", fontsize=10)
        ax_hm.xaxis.tick_top()

        ax_hm.set_yticks(range(len(sirali_ogr)))
        ax_hm.set_yticklabels([f"{i+1}. {o}" for i, o in enumerate(sirali_ogr)], fontsize=9.5, fontweight="bold")

        for r in range(olcum_matrisi.shape[0]):
            for c in range(olcum_matrisi.shape[1]):
                val = olcum_matrisi[r, c]
                if not pd.isna(val):
                    yazi_renk = "white" if val >= 68 else "#1e293b"
                    fark_eki = ""
                    if c > 0 and not pd.isna(olcum_matrisi[r, c - 1]):
                        f = int(val - olcum_matrisi[r, c - 1])
                        fark_eki = f" ({f:+d})"
                    ax_hm.text(c, r, f"{int(val)}{fark_eki}", ha="center", va="center", color=yazi_renk, fontsize=8.5, fontweight="bold")
                else:
                    ax_hm.text(c, r, "-", ha="center", va="center", color="#94a3b8", fontsize=8.5)

        cbar = plt.colorbar(im, ax=ax_hm, fraction=0.025, pad=0.02)
        cbar.set_label("Dakikada Doğru Kelime Sayısı (DOKS)", fontsize=9)
        plt.tight_layout()
        st.pyplot(fig_hm)

        st.divider()

        # 2) İLK VS SON ÖLÇÜM SINIF KARŞILAŞTIRMASI & BİREYSEL DEĞİŞİM EĞRİSİ
        col_d1, col_d2 = st.columns([1.3, 1])

        with col_d1:
            st.markdown("### 📊 Öğrenci Bazlı İlk vs. Son DOKS Karşılaştırması")
            sirali_ozet = olculen_df.sort_values(by="Son DOKS", ascending=True)
            fig_bar, ax_bar = plt.subplots(figsize=(7, max(5.5, len(sirali_ozet) * 0.28)))
            y_pos = range(len(sirali_ozet))

            ax_bar.barh([y - 0.18 for y in y_pos], sirali_ozet["İlk DOKS"], height=0.35, label="İlk Ölçüm", color="#94a3b8")
            ax_bar.barh([y + 0.18 for y in y_pos], sirali_ozet["Son DOKS"], height=0.35, label="Son Ölçüm", color="#2563eb")
            ax_bar.axvline(son_sinif_ort, color="#dc2626", linestyle="--", linewidth=1.1, label=f"Sınıf Ort. ({son_sinif_ort:.1f})")

            ax_bar.set_yticks(list(y_pos))
            ax_bar.set_yticklabels(sirali_ozet["Öğrenci"], fontsize=8.5)
            ax_bar.set_xlabel("Dakikada Doğru Kelime Sayısı")
            ax_bar.legend(loc="lower right", fontsize=8.5)
            ax_bar.spines["top"].set_visible(False)
            ax_bar.spines["right"].set_visible(False)
            plt.tight_layout()
            st.pyplot(fig_bar)

        with col_d2:
            st.markdown("### 📈 Bireysel DOKS Gelişim Eğrisi")
            secili_doks_ogr = st.selectbox("Öğrenci Seçin (Bireysel Değişim):", sirali_ogr, key="doks_ogr_sec")
            ogr_doks_seri = df_okuma[df_okuma["Ogrenci"] == secili_doks_ogr].copy()

            if not ogr_doks_seri.empty:
                ilk_v = int(ogr_doks_seri.iloc[0]["DOKS"])
                son_v = int(ogr_doks_seri.iloc[-1]["DOKS"])
                st.metric(
                    f"{secili_doks_ogr} — Son Okuma Hızı",
                    f"{son_v} kelime/dk",
                    delta=f"{son_v - ilk_v:+d} kelime (Başlangıç: {ilk_v})"
                )

                fig_line, ax_line = plt.subplots(figsize=(5, 3.2))
                ax_line.plot(
                    ogr_doks_seri["OlcumNo"],
                    ogr_doks_seri["DOKS"],
                    marker="o",
                    linewidth=2.5,
                    markersize=7,
                    color="#7c3aed"
                )
                ax_line.axhline(son_sinif_ort, color="#94a3b8", linestyle="--", linewidth=1, label=f"Sınıf Ort. ({son_sinif_ort:.1f})")
                for _, row in ogr_doks_seri.iterrows():
                    etiket = f"{int(row['DOKS'])}"
                    if pd.notna(row["Dogruluk"]):
                        etiket += f"\n(%{row['Dogruluk']:.0f})"
                    ax_line.annotate(etiket, (row["OlcumNo"], row["DOKS"]), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8.5, fontweight="bold")

                ax_line.set_xticks(ogr_doks_seri["OlcumNo"])
                ax_line.set_xticklabels([f"{int(n)}. Ölçüm" for n in ogr_doks_seri["OlcumNo"]])
                ax_line.set_ylabel("Kelime / Dakika")
                ax_line.set_ylim(0, max(110, ogr_doks_seri["DOKS"].max() + 20))
                ax_line.legend(fontsize=8)
                ax_line.spines["top"].set_visible(False)
                ax_line.spines["right"].set_visible(False)
                plt.tight_layout()
                st.pyplot(fig_line)

                st.dataframe(
                    ogr_doks_seri[["Tarih", "DOKS", "Dogruluk", "Not"]].rename(columns={"Dogruluk": "Doğruluk (%)"}),
                    use_container_width=True,
                    hide_index=True
                )

        with st.expander("📋 Tüm Sınıf DOKS Özet Tablosunu Görüntüle"):
            st.dataframe(df_doks_ozet, use_container_width=True, hide_index=True)

# -------------------- 3. SEKME: ÖĞRENCİ PROFİLİ & AI KARNE --------------------
with tab_ogrenci:
    secili_ogr = st.selectbox("Öğrenci Seçin:", ogrenci_listesi, key="profil_ogr_sec")
    ogr_df = df_kayit[df_kayit["Ogrenci"] == secili_ogr]

    if ogr_df.empty:
        st.warning("Bu öğrenci için henüz kayıt bulunmuyor.")
    else:
        doks_satir = df_doks_ozet[df_doks_ozet["Öğrenci"] == secili_ogr].iloc[0] if not df_doks_ozet.empty else None
        p1, p2, p3 = st.columns(3)
        p1.metric("Genel Gelişim Ortalaması", f"{ogr_df['Puan'].mean():.2f} / 4.00")
        p2.metric("Toplam Gözlem / Kanıt", len(ogr_df))
        if doks_satir is not None and pd.notna(doks_satir["Son DOKS"]):
            p3.metric(
                "Güncel Okuma Hızı (DOKS)",
                f"{int(doks_satir['Son DOKS'])} kelime/dk",
                delta=f"{int(doks_satir['Değişim (Kelime)']):+d} kelime"
            )
        else:
            p3.metric("Güncel Okuma Hızı (DOKS)", "Veri Yok")

        st.divider()
        st.subheader("🤖 Yapay Zekâ (Flash-Lite) e-Okul & Veli Gelişim Yorumu")
        if st.button("✨ AI ile Gelişim Raporu Yorumu Oluştur", type="primary"):
            with st.spinner("Flash-Lite modeli öğrenci verilerini analiz ediyor..."):
                yorum = gemini_karne_yorumu_uret(secili_ogr, ogr_df, doks_satir)
                st.session_state[f"ai_yorum_{secili_ogr}"] = yorum

        mevcut_yorum = st.session_state.get(f"ai_yorum_{secili_ogr}", "")
        st.text_area(
            "Oluşturulan Gelişim Raporu (Düzenleyip kopyalayabilirsiniz):",
            value=mevcut_yorum,
            height=130
        )

        st.subheader("Öğrenme Çıktısı Bazlı Ortalamalar")
        hedef_ozet = (
            ogr_df.groupby(["Alan", "Ders", "Hedef"])["Puan"]
            .agg(["count", "mean"])
            .reset_index()
            .rename(columns={"count": "Gözlem", "mean": "Ortalama"})
        )
        hedef_ozet["Ortalama"] = hedef_ozet["Ortalama"].round(2)
        st.dataframe(hedef_ozet, use_container_width=True, hide_index=True)
