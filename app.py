import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

st.set_page_config(page_title="2-C Bütüncül Gelişim Analiz Paneli", layout="wide")

# API ve Tablo Bilgileri (Streamlit Secrets üzerinden güvenli okuma)
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("SHEET_ID", "BURAYA_GOOGLE_SHEETS_ID_YAZIN")


@st.cache_data(ttl=60)
def verileri_yukle(sheet_id: str):
    kayit_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Kayitlar"
    ogr_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Ogrenciler"

    df_k = pd.read_csv(kayit_url)
    # Sütun isimlerini standartlaştır
    beklenen_sutunlar = ["Tarih", "Ogrenci", "Alan", "Ders", "Hedef", "Puan", "Not"]
    if len(df_k.columns) >= 7:
        df_k = df_k.iloc[:, :7]
        df_k.columns = beklenen_sutunlar

    df_k["Puan"] = pd.to_numeric(df_k["Puan"], errors="coerce")
    df_k = df_k.dropna(subset=["Ogrenci", "Puan"])
    df_k["Ogrenci"] = df_k["Ogrenci"].astype(str).str.strip()
    df_k["Not"] = df_k["Not"].fillna("").astype(str)
    df_k["Tarih"] = df_k["Tarih"].fillna("").astype(str)
    df_k["Hedef"] = df_k["Hedef"].fillna("").astype(str)
    df_k["Ders"] = df_k["Ders"].fillna("").astype(str)
    df_k["Alan"] = df_k["Alan"].fillna("").astype(str)

    df_o = pd.read_csv(ogr_url, header=None)
    ogrenciler = df_o[0].dropna().astype(str).str.strip().tolist()
    return df_k, ogrenciler


def ogrenci_verisini_ozetle(df_ogr: pd.DataFrame) -> str:
    if df_ogr.empty:
        return "Bu öğrenci için henüz kayıt bulunmuyor."

    ozet_satirlar = []

    alan_ort = df_ogr.groupby("Alan")["Puan"].mean().round(2).to_dict()
    ozet_satirlar.append(f"Gelişim Alanı Ortalamaları (4 üzerinden): {alan_ort}")

    okuma_df = df_ogr[df_ogr["Hedef"].str.contains("okuma|akıcı", case=False, na=False)]
    if not okuma_df.empty:
        doks_gecmisi = []
        for _, r in okuma_df.iterrows():
            temiz_not = str(r["Not"]).split("| Kanıt:")[0].strip()
            doks_gecmisi.append(f"{r['Tarih'][:10]}: {temiz_not} (Puan: {r['Puan']}/4)")
        ozet_satirlar.append("Okuma Akıcılığı (DOKS) Geçmişi:\n- " + "\n- ".join(doks_gecmisi))

    srsd_df = df_ogr[df_ogr["Not"].str.contains(r"\[SRSD", case=False, na=False)]
    if not srsd_df.empty:
        srsd_list = []
        for _, r in srsd_df.iterrows():
            temiz_not = str(r["Not"]).split("| Kanıt:")[0].strip()
            srsd_list.append(f"{temiz_not} -> Puan: {r['Puan']}/4")
        ozet_satirlar.append("SRSD Yazma Analizi Sonuçları:\n- " + "\n- ".join(srsd_list))

    diger_df = df_ogr[~df_ogr.index.isin(okuma_df.index) & ~df_ogr.index.isin(srsd_df.index)]
    if not diger_df.empty:
        diger_list = []
        for _, r in diger_df.tail(15).iterrows():
            temiz_not = str(r["Not"]).split("| Kanıt:")[0].strip()
            diger_list.append(f"[{r['Ders']}] {r['Hedef']} -> Puan: {r['Puan']}/4 ({temiz_not})")
        ozet_satirlar.append("Akademik / Oyun / Çalışma Kâğıdı Gözlemleri:\n- " + "\n- ".join(diger_list))

    return "\n\n".join(ozet_satirlar)


def gemini_karne_yorumu_uret(ogrenci_adi: str, veri_ozeti: str, ton: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("Streamlit Secrets içinde GEMINI_API_KEY bulunamadı.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    prompt = f"""
    Sen Türkiye Yüzyılı Maarif Modeli (TYMM) bütüncül değerlendirme yaklaşımını benimseyen deneyimli bir 2. sınıf sınıf öğretmenisin.
    Aşağıdaki somut sınıf içi gözlem, okuma hızı (DOKS), oyun performansı ve SRSD yazma analizi verilerine dayanarak **{ogrenci_adi}** adlı öğrencinin velisine sunulacak bireysel gelişim karnesi değerlendirme metnini yaz.

    Kurallar:
    1. Basmakalıp ("Çok zeki ama çalışmıyor", "Başarılarının devamını dilerim") ifadeler KESİNLİKLE kullanma.
    2. Doğrudan verideki somut kanıtlara atıf yap (Örn: okuma hızındaki artışı, hikâye kurgusundaki başarısını veya kelimeler arası boşluk/onluk bozma gibi spesifik gelişim alanlarını somutlaştır).
    3. Yazma gelişimi verisi varsa; çocuğun hayal gücü/kurgu becerisi ile mekanik yazım/boşluk becerisini birbirinden ayırarak veliyi doğru yönlendir.
    4. Metin üslubu: **{ton}**.
    5. Uzunluk: Veli karnesi kutusuna tam sığacak şekilde 4-5 cümlelik (yaklaşık 70-95 kelime) akıcı bir paragraf yaz. Sadece yorum metnini döndür, başlık ekleme.

    ÖĞRENCİ VERİLERİ:
    {veri_ozeti}
    """

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.35}
    }

    resp = requests.post(url, json=payload, timeout=30)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "API Hatası"))

    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


# ==================== ANA UYGULAMA AKIŞI ====================
st.title("📊 2-C Sınıfı Bütüncül Gelişim & AI Analiz Paneli")

if not GEMINI_API_KEY:
    st.warning("⚠️ AI yorum üreticisini kullanmak için Streamlit Cloud > Settings > Secrets bölümüne `GEMINI_API_KEY` ekleyin.")

try:
    df_kayitlar, ogrenci_listesi = verileri_yukle(SHEET_ID)
except Exception as e:
    st.error(f"Google Sheets verisi yüklenemedi. `SHEET_ID` değerini ve tablonun paylaşım ayarını ('Bağlantıya sahip herkes görüntüleyebilir') kontrol edin.\n\nHata detayı: {e}")
    st.stop()

tab1, tab2, tab3 = st.tabs(["📈 Sınıf & Ders Analizi", "👤 Bireysel Öğrenci Karnesi", "🧠 AI Pedagog & Karne Yorumu"])

# ---------------- SEKME 1: SINIF ANALİZİ ----------------
with tab1:
    c1, c2, c3 = st.columns(3)
    c1.metric("Toplam Gözlem / Kanıt Kaydı", len(df_kayitlar))
    c2.metric("Kayıtlı Öğrenci Sayısı", len(ogrenci_listesi))
    c3.metric("Sınıf Genel Ortalaması", f"{df_kayitlar['Puan'].mean():.2f} / 4.00")

    st.subheader("Gelişim Alanlarına Göre Sınıf Ortalaması")
    st.bar_chart(df_kayitlar.groupby("Alan")["Puan"].mean())

    st.subheader("Son Girilen 25 Değerlendirme Kaydı")
    st.dataframe(df_kayitlar.tail(25).iloc[::-1], use_container_width=True, hide_index=True)

# ---------------- SEKME 2: BİREYSEL ÖĞRENCİ İNCELEME ----------------
with tab2:
    secim_ogr = st.selectbox("İncelenecek Öğrenci:", ogrenci_listesi, key="tab2_ogr")
    df_tek = df_kayitlar[df_kayitlar["Ogrenci"] == secim_ogr]

    if df_tek.empty:
        st.info("Bu öğrenci için henüz kayıt bulunmuyor.")
    else:
        st.metric(f"{secim_ogr} — Genel Ortalama", f"{df_tek['Puan'].mean():.2f} / 4.00", f"{len(df_tek)} kayıt")
        st.bar_chart(df_tek.groupby("Ders")["Puan"].mean())
        st.dataframe(df_tek.iloc[::-1], use_container_width=True, hide_index=True)

# ---------------- SEKME 3: AI PEDAGOG & KARNE YORUMU ----------------
with tab3:
    st.subheader("🧠 AI Pedagog & Bireysel Gelişim Raporu Asistanı")
    mod = st.radio("Çalışma Modu:", ["👤 Tekli Öğrenci Yorumu Üret", "📚 Tüm Sınıf İçin Toplu Yorum Üret (CSV İndir)"], horizontal=True)
    ton = st.selectbox("Geri Bildirim Üslubu:", [
        "Yapıcı, Sıcak ve Veliye Ev Önerisi Sunan",
        "Resmi ve Akademik Odaklı",
        "Motive Edici ve Güçlü Yönleri Öne Çıkaran"
    ])
    st.divider()

    if mod.startswith("👤"):
        secili_ogr = st.selectbox("Öğrenci Seçin:", ogrenci_listesi, key="ai_ogr")
        df_ogr = df_kayitlar[df_kayitlar["Ogrenci"] == secili_ogr]

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**📊 AI'ya Gönderilecek Veri Özeti**")
            veri_ozeti = ogrenci_verisini_ozetle(df_ogr)
            st.text_area("Sistem Tarafından Derlenen Kanıtlar", veri_ozeti, height=260, disabled=True)

        with col2:
            st.markdown("**✍️ Üretilen Veli Karnesi Değerlendirmesi**")
            if st.button("🤖 Pedagojik Yorum Üret", type="primary", use_container_width=True):
                if df_ogr.empty:
                    st.warning("Bu öğrenciye ait veri bulunmuyor.")
                else:
                    with st.spinner(f"{secili_ogr} verileri analiz ediliyor..."):
                        try:
                            yorum = gemini_karne_yorumu_uret(secili_ogr, veri_ozeti, ton)
                            st.session_state[f"yorum_{secili_ogr}"] = yorum
                        except Exception as e:
                            st.error(f"Hata oluştu: {e}")

            mevcut_yorum = st.session_state.get(f"yorum_{secili_ogr}", "")
            st.text_area("Üretilen Metin (Kopyalayıp Veli Karnesi PDF ekranına yapıştırabilirsiniz):", value=mevcut_yorum, height=215)

    else:
        st.info("💡 Ücretsiz API hız limitine (15 istek/dakika) takılmamak için her öğrenci arasında otomatik 4.2 saniye beklenir.")
        if st.button("🚀 Tüm Sınıfın Karne Yorumlarını Oluştur", type="primary"):
            ilerleme = st.progress(0)
            durum = st.empty()
            sonuclar = []

            for idx, ogr in enumerate(ogrenci_listesi):
                durum.text(f"⏳ ({idx + 1}/{len(ogrenci_listesi)}) {ogr} analiz ediliyor...")
                df_ogr = df_kayitlar[df_kayitlar["Ogrenci"] == ogr]

                if df_ogr.empty:
                    sonuclar.append({"Öğrenci": ogr, "Kayıt Sayısı": 0, "Karne Yorumu": "Henüz yeterli gözlem verisi girilmemiştir."})
                else:
                    ozet = ogrenci_verisini_ozetle(df_ogr)
                    try:
                        yorum = gemini_karne_yorumu_uret(ogr, ozet, ton)
                        sonuclar.append({"Öğrenci": ogr, "Kayıt Sayısı": len(df_ogr), "Karne Yorumu": yorum})
                    except Exception as e:
                        sonuclar.append({"Öğrenci": ogr, "Kayıt Sayısı": len(df_ogr), "Karne Yorumu": f"Hata: {e}"})

                    if idx < len(ogrenci_listesi) - 1:
                        time.sleep(4.2)

                ilerleme.progress((idx + 1) / len(ogrenci_listesi))

            durum.success("✅ Tüm sınıfın pedagojik değerlendirme metinleri hazır!")
            df_sonuc = pd.DataFrame(sonuclar)
            st.dataframe(df_sonuc, use_container_width=True, hide_index=True)

            csv_veri = df_sonuc.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 Tüm Yorumları Excel (CSV) Olarak İndir",
                data=csv_veri,
                file_name=f"2C_AI_Karne_Yorumlari_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
