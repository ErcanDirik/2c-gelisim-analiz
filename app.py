import streamlit as st
import pandas as pd
import requests
import json
import time
from datetime import datetime

# API Anahtarınızı Streamlit Secrets'tan veya doğrudan buradan tanımlayın
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "AIzaSyDM0DfD_7D0R-fKdS82iEb_cTkZoqCEQEQ")

def ogrenci_verisini_ozetle(df_ogr: pd.DataFrame) -> str:
    """Öğrencinin Kayitlar tablosundaki tüm performansını AI için yapılandırılmış metne dönüştürür."""
    if df_ogr.empty:
        return "Bu öğrenci için henüz kayıt bulunmuyor."
    
    ozet_satirlar = []
    
    # 1. Alan Bazlı Ortalamalar
    alan_ort = df_ogr.groupby("Alan")["Puan"].mean().round(2).to_dict()
    ozet_satirlar.append(f"Gelişim Alanı Ortalamaları (4 üzerinden): {alan_ort}")
    
    # 2. Okuma Akıcılığı (DOKS) Seyri
    okuma_df = df_ogr[df_ogr["Hedef"].str.contains("okuma|akıcı", case=False, na=False)]
    if not okuma_df.empty:
        doks_gecmisi = []
        for _, r in okuma_df.iterrows():
            # Kanıt linkini temizle, sadece DOKS ve gözlem notunu al
            temiz_not = str(r["Not"]).split("| Kanıt:")[0].strip()
            doks_gecmisi.append(f"{r['Tarih'][:10]}: {temiz_not} (Puan: {r['Puan']}/4)")
        ozet_satirlar.append("Okuma Akıcılığı (DOKS) Geçmişi:\n- " + "\n- ".join(doks_gecmisi))
        
    # 3. SRSD 4 Boyutlu Yazma Gelişimi Bulguları
    srsd_df = df_ogr[df_ogr["Not"].str.contains(r"\[SRSD", case=False, na=False)]
    if not srsd_df.empty:
        srsd_list = []
        for _, r in srsd_df.iterrows():
            temiz_not = str(r["Not"]).split("| Kanıt:")[0].strip()
            srsd_list.append(f"{temiz_not} -> Puan: {r['Puan']}/4")
        ozet_satirlar.append("SRSD Yazma Analizi Sonuçları:\n- " + "\n- ".join(srsd_list))
        
    # 4. Diğer Akademik, Oyun ve AI Çalışma Kâğıdı Gözlemleri
    diger_df = df_ogr[~df_ogr.index.isin(okuma_df.index) & ~df_ogr.index.isin(srsd_df.index)]
    if not diger_df.empty:
        diger_list = []
        for _, r in diger_df.tail(15).iterrows(): # Son 15 gözlem
            temiz_not = str(r["Not"]).split("| Kanıt:")[0].strip()
            diger_list.append(f"[{r['Ders']}] {r['Hedef']} -> Puan: {r['Puan']}/4 ({temiz_not})")
        ozet_satirlar.append("Akademik / Oyun / Çalışma Kâğıdı Gözlemleri:\n- " + "\n- ".join(diger_list))
        
    return "\n\n".join(ozet_satirlar)


def gemini_karne_yorumu_uret(ogrenci_adi: str, veri_ozeti: str, ton: str = "Yapıcı ve Dengeli") -> str:
    """Gemini 2.5 Flash API kullanarak kişiselleştirilmiş pedagojik karne yorumu üretir."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Sen Türkiye Yüzyılı Maarif Modeli (TYMM) bütüncül değerlendirme yaklaşımını benimseyen deneyimli bir 2. sınıf sınıf öğretmenisin.
    Aşağıdaki somut sınıf içi gözlem, okuma hızı (DOKS), oyun performansı ve SRSD yazma analizi verilerine dayanarak **{ogrenci_adi}** adlı öğrencinin velisine sunulacak bireysel gelişim karnesi değerlendirme metnini yaz.

    Kurallar:
    1. Basmakalıp ("Çok zeki ama çalışmıyor", "Başarılarının devamını dilerim") ifadeler KESİNLİKLE kullanma.
    2. Doğrudan verideki somut kanıtlara atıf yap (Örn: okuma hızındaki artışı, hikâye kurgusundaki başarısını veya kelimeler arası boşluk/onluk bozma gibi spesifik gelişim alanlarını somutlaştır).
    3. Yazma gelişimi verisi varsa; çocuğun hayal gücü/kurgu becerisi ile mekanik yazım/boşluk becerisini birbirinden ayırarak veliyi doğru yönlendir.
    4. Metin üslubu: **{ton}**.
    5. Uzunluk: Veli karnesi kutusuna tam sığacak şekilde 4-5 cümlelik (yaklaşık 70-95 kelime) akıcı, tek veya iki paragraf halinde Türkçe bir metin yaz. Sadece yorum metnini döndür, başlık ekleme.

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


def ai_pedagog_modulu_goster(df_kayitlar: pd.DataFrame, ogrenci_listesi: list, gs_client=None, sheet_id: str = None):
    """Streamlit arayüzünde AI Pedagog & Karne Yorumu Üretici sekmesini çizer."""
    st.subheader("🧠 AI Pedagog & Bireysel Gelişim Raporu Asistanı")
    st.caption("Öğrencinin DOKS ivmesini, SRSD 4 boyutlu yazma profilini ve oyun/kâğıt analizlerini sentezleyerek kişiselleştirilmiş veli geri bildirimi üretir.")

    mod = st.radio("Çalışma Modu Seçin:", ["👤 Tekli Öğrenci İncele & Yorum Üret", "📚 Tüm Sınıf İçin Toplu Yorum Üret (Excel İndir)"], horizontal=True)
    ton = st.selectbox("Geri Bildirim Tonu:", ["Yapıcı, Sıcak ve Veliye Ev Önerisi Sunan", "Resmi ve Akademik Odaklı", "Motive Edici ve Güçlü Yönleri Öne Çıkaran"])

    st.divider()

    # ---------------- MOD 1: TEKLİ ÖĞRENCİ ----------------
    if mod.startswith("👤"):
        secili_ogr = st.selectbox("Öğrenci Seçin:", ogrenci_listesi)
        df_ogr = df_kayitlar[df_kayitlar["Ogrenci"] == secili_ogr]

        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown("**📊 AI'ya Gönderilecek Ham Veri Özeti**")
            veri_ozeti = ogrenci_verisini_ozetle(df_ogr)
            st.text_area("Sistem Tarafından Derlenen Kanıtlar", veri_ozeti, height=260, disabled=True)

        with col2:
            st.markdown("**✍️ Üretilen Veli Karnesi Değerlendirmesi**")
            if st.button("🤖 Pedagojik Yorum Üret", type="primary", use_container_width=True):
                if df_ogr.empty:
                    st.warning("Bu öğrenciye ait veri bulunmadığı için yorum üretilemiyor.")
                else:
                    with st.spinner(f"{secili_ogr} verileri analiz ediliyor..."):
                        try:
                            yorum = gemini_karne_yorumu_uret(secili_ogr, veri_ozeti, ton)
                            st.session_state[f"yorum_{secili_ogr}"] = yorum
                        except Exception as e:
                            st.error(f"Hata oluştu: {e}")

            mevcut_yorum = st.session_state.get(f"yorum_{secili_ogr}", "")
            duzenlenen_yorum = st.text_area("Metni düzenleyip kopyalayabilir veya Sheets'e kaydedebilirsiniz:", value=mevcut_yorum, height=195)

            if duzenlenen_yorum and gs_client and sheet_id:
                if st.button("💾 Onayla ve Google Sheets 'Karne_Yorumlari' Sekmesine Kaydet", use_container_width=True):
                    try:
                        sh = gs_client.open_by_key(sheet_id)
                        try:
                            ws = sh.worksheet("Karne_Yorumlari")
                        except Exception:
                            ws = sh.add_worksheet(title="Karne_Yorumlari", rows=100, cols=3)
                            ws.append_row(["Ogrenci", "Tarih", "Pedagojik_Yorum"])
                        
                        tarih_str = datetime.now().strftime("%d.%m.%Y %H:%M")
                        ws.append_row([secili_ogr, tarih_str, duzenlenen_yorum])
                        st.success(f"✅ {secili_ogr} yorumu Google Sheets'e kaydedildi!")
                    except Exception as e:
                        st.error(f"Sheets kayıt hatası: {e}")

    # ---------------- MOD 2: TÜM SINIF TOPLU ÜRETİM ----------------
    else:
        st.info("💡 Ücretsiz API hız limitine (15 istek/dakika) takılmamak için sistem her öğrenci arasında otomatik 4.2 saniye bekler. 28 öğrencilik sınıf yaklaşık 2 dakikada tamamlanır.")
        
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
                    
                    # Ücretsiz API 15 RPM limitini korumak için güvenli bekleme
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
