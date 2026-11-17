import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import re
import time
from datetime import datetime

st.set_page_config(
    page_title="2-C Bütüncül Gelişim & Analitik Raporlama Merkezi",
    page_icon="📊",
    layout="wide"
)

# API ve Tablo Bilgileri (Streamlit Secrets)
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
SHEET_ID = st.secrets.get("SHEET_ID", "")


@st.cache_data(ttl=60)
def verileri_yukle(sheet_id: str):
    kayit_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Kayitlar"
    ogr_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Ogrenciler"

    df_k = pd.read_csv(kayit_url)
    beklenen_sutunlar = ["Tarih", "Ogrenci", "Alan", "Ders", "Hedef", "Puan", "Not"]
    if len(df_k.columns) >= 7:
        df_k = df_k.iloc[:, :7]
        df_k.columns = beklenen_sutunlar

    df_k["Puan"] = pd.to_numeric(df_k["Puan"], errors="coerce")
    df_k = df_k.dropna(subset=["Ogrenci", "Puan"])
    for col in ["Ogrenci", "Alan", "Ders", "Hedef", "Not", "Tarih"]:
        df_k[col] = df_k[col].fillna("").astype(str).str.strip()

    # Tarih ayrıştırma (grafik sıralaması için)
    df_k["Tarih_DT"] = pd.to_datetime(df_k["Tarih"], format="%d.%m.%Y %H:%M", errors="coerce")
    df_k["Tarih_Kisa"] = df_k["Tarih"].str.slice(0, 10)

    # Not içinden Drive Kanıt linkini ve temiz açıklamayı ayır
    df_k["Kanit_URL"] = df_k["Not"].apply(
        lambda x: x.split("| Kanıt:")[1].strip() if "| Kanıt:" in x else ""
    )
    df_k["Temiz_Not"] = df_k["Not"].apply(
        lambda x: x.split("| Kanıt:")[0].strip()
    )

    df_o = pd.read_csv(ogr_url, header=None)
    ogrenciler = df_o[0].dropna().astype(str).str.strip().tolist()
    # Başlık satırı varsa temizle
    if ogrenciler and ogrenciler[0].lower() in ["ogrenci", "öğrenci", "ad soyad", "isim"]:
        ogrenciler = ogrenciler[1:]

    return df_k, ogrenciler


def doks_verisi_cikar(df_ogr: pd.DataFrame) -> pd.DataFrame:
    """Kayıtların içinden DOKS (Dakikada Okunan Doğru Kelime) sayısal değerlerini ayıklar."""
    okuma_df = df_ogr[
        df_ogr["Hedef"].str.contains("okuma|akıcı", case=False, na=False) |
        df_ogr["Temiz_Not"].str.contains("DOKS|kelime", case=False, na=False)
    ].copy()

    if okuma_df.empty:
        return pd.DataFrame()

    def sayi_bul(metin):
        eslesme = re.search(r"(\d+)\s*(?:DOKS|kelime)", metin, re.IGNORECASE)
        if eslesme:
            return int(eslesme.group(1))
        eslesme2 = re.search(r"DOKS[:\s]*(\d+)", metin, re.IGNORECASE)
        return int(eslesme2.group(1)) if eslesme2 else None

    okuma_df["DOKS"] = okuma_df["Temiz_Not"].apply(sayi_bul)
    return okuma_df.dropna(subset=["DOKS"]).sort_values("Tarih_DT")


def srsd_profili_cikar(df_ogr: pd.DataFrame) -> pd.DataFrame:
    """[SRSD ...] etiketli 4 boyutlu yazma değerlendirmelerini özetler."""
    srsd_df = df_ogr[df_ogr["Temiz_Not"].str.contains(r"\[SRSD", case=False, na=False)].copy()
    if srsd_df.empty:
        return pd.DataFrame()

    def boyut_etiketi(metin):
        if "[SRSD Kurgu]" in metin:
            return "1. Hikâye Kurgusu"
        if "[SRSD Cümle/Akış]" in metin:
            return "2. Cümle & Akış"
        if "[SRSD İmla/Noktalama]" in metin:
            return "3. İmla & Noktalama"
        if "[SRSD Boşluk/Düzen]" in metin:
            return "4. Kelime Boşluğu & Düzen"
        return "Diğer Yazma"

    srsd_df["Boyut"] = srsd_df["Temiz_Not"].apply(boyut_etiketi)
    return srsd_df.groupby("Boyut", as_index=False)["Puan"].mean().round(2)


def ogrenci_verisini_ozetle(df_ogr: pd.DataFrame) -> str:
    if df_ogr.empty:
        return "Bu öğrenci için henüz kayıt bulunmuyor."

    ozet_satirlar = []
    alan_ort = df_ogr.groupby("Alan")["Puan"].mean().round(2).to_dict()
    ozet_satirlar.append(f"Gelişim Alanı Ortalamaları (4 üzerinden): {alan_ort}")

    doks_df = doks_verisi_cikar(df_ogr)
    if not doks_df.empty:
        doks_list = [f"{r['Tarih_Kisa']}: {int(r['DOKS'])} kelime/dk (Puan: {r['Puan']}/4)" for _, r in doks_df.iterrows()]
        ozet_satirlar.append("Okuma Akıcılığı (DOKS) Seyri:\n- " + "\n- ".join(doks_list))

    srsd_df = df_ogr[df_ogr["Temiz_Not"].str.contains(r"\[SRSD", case=False, na=False)]
    if not srsd_df.empty:
        srsd_list = [f"{r['Temiz_Not']} -> Puan: {r['Puan']}/4" for _, r in srsd_df.iterrows()]
        ozet_satirlar.append("SRSD 4 Boyutlu Yazma Analizi:\n- " + "\n- ".join(srsd_list))

    diger_df = df_ogr[~df_ogr.index.isin(srsd_df.index)]
    if not diger_df.empty:
        diger_list = [f"[{r['Ders']}] {r['Hedef']} -> Puan: {r['Puan']}/4 ({r['Temiz_Not']})" for _, r in diger_df.tail(15).iterrows()]
        ozet_satirlar.append("Son Gözlem, Oyun ve Çalışma Kâğıdı Kanıtları:\n- " + "\n- ".join(diger_list))

    return "\n\n".join(ozet_satirlar)


def gemini_karne_yorumu_uret(ogrenci_adi: str, veri_ozeti: str, ton: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("Streamlit Secrets içinde GEMINI_API_KEY tanımlı değil.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"""
    Sen Türkiye Yüzyılı Maarif Modeli (TYMM) bütüncül değerlendirme yaklaşımını benimseyen uzman bir 2. sınıf sınıf öğretmenisin.
    Aşağıdaki somut gözlem, DOKS okuma hızı, oyun performansı ve SRSD yazma analizi verilerine dayanarak **{ogrenci_adi}** adlı öğrencinin velisine sunulacak profesyonel gelişim karnesi değerlendirmesini yaz.

    Kurallar:
    1. Basmakalıp ifadeler kullanma; doğrudan verideki somut göstergelere atıf yap.
    2. Yazma verisi varsa kurgu/yaratıcılık ile imla/kelime boşluğu becerisini ayrı değerlendir.
    3. Üslup: **{ton}**.
    4. Uzunluk: 4-5 cümlelik (75-100 kelime) akıcı bir paragraf olsun. Sadece yorum metnini döndür.

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


def kurumsal_karne_html_olustur(ogrenci: str, df_ogr: pd.DataFrame, yorum: str) -> str:
    """Tarayıcıda açılıp tek tıkla A4 PDF olarak yazdırılabilen kurumsal karne şablonu üretir."""
    bugun = datetime.now().strftime("%d.%m.%Y")
    genel_ort = f"{df_ogr['Puan'].mean():.2f}"

    ders_tablo = df_ogr.groupby(["Alan", "Ders", "Hedef"], as_index=False)["Puan"].mean().round(2)
    satirlar_html = ""
    for _, r in ders_tablo.iterrows():
        duzey = "Çok İyi" if r["Puan"] >= 3.5 else ("İyi" if r["Puan"] >= 2.75 else ("Yeterli" if r["Puan"] >= 2.0 else "Desteklenmeli"))
        renk = "#16a34a" if r["Puan"] >= 3.5 else ("#2563eb" if r["Puan"] >= 2.75 else ("#d97706" if r["Puan"] >= 2.0 else "#dc2626"))
        satirlar_html += f"""
        <tr>
          <td>{r['Alan']}</td>
          <td><strong>{r['Ders']}</strong></td>
          <td>{r['Hedef']}</td>
          <td style="text-align:center; font-weight:bold;">{r['Puan']} / 4.00</td>
          <td style="text-align:center;"><span style="background:{renk}; color:white; padding:2px 8px; border-radius:10px; font-size:11px;">{duzey}</span></td>
        </tr>
        """

    yorum_blok = yorum if yorum else "Öğrencimizin dönem içi sınıf katılımı, akademik kazanım süreci ve bireysel gelişim basamakları bütüncül olarak takip edilmektedir."

    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
      <meta charset="UTF-8">
      <title>{ogrenci} - Bütüncül Gelişim Karnesi</title>
      <style>
        body {{ font-family: 'Segoe UI', Tahoma, sans-serif; color: #1e293b; margin: 24px; line-height: 1.5; }}
        .ust-banner {{ background: linear-gradient(135deg, #1e3a8a, #3b82f6); color: white; padding: 18px 24px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center; }}
        .ust-banner h1 {{ margin: 0; font-size: 20px; }}
        .bilgi-kutular {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 16px 0; }}
        .kart {{ background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; padding: 12px; text-align: center; }}
        .kart span {{ font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: bold; display: block; }}
        .kart strong {{ font-size: 17px; color: #0f172a; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12.5px; }}
        th {{ background: #e2e8f0; color: #1e293b; padding: 8px; text-align: left; border: 1px solid #cbd5e1; }}
        td {{ padding: 7px 8px; border: 1px solid #cbd5e1; }}
        .yorum-kutusu {{ background: #f0fdf4; border-left: 5px solid #16a34a; padding: 14px 18px; border-radius: 8px; margin-top: 18px; }}
        .imza {{ margin-top: 28px; display: flex; justify-content: space-between; font-size: 13px; color: #475569; }}
        @media print {{ body {{ margin: 10px; }} }}
      </style>
    </head>
    <body>
      <div class="ust-banner">
        <div>
          <h1>2-C SINIFI BÜTÜNCÜL GELİŞİM VE PORTFOLYO RAPORU</h1>
          <div style="font-size:13px; opacity:0.9;">Türkiye Yüzyılı Maarif Modeli Süreç Odaklı Değerlendirme</div>
        </div>
        <div style="text-align:right; font-size:13px;">Düzenleme Tarihi<br><strong>{bugun}</strong></div>
      </div>

      <div class="bilgi-kutular">
        <div class="kart"><span>Öğrenci Adı Soyadı</span><strong>{ogrenci}</strong></div>
        <div class="kart"><span>Değerlendirilen Kanıt Sayısı</span><strong>{len(df_ogr)} Kayıt</strong></div>
        <div class="kart"><span>Genel Gelişim Ortalaması</span><strong>{genel_ort} / 4.00</strong></div>
      </div>

      <h3 style="margin-bottom:4px; color:#1e3a8a; font-size:15px;">📋 Öğrenme Çıktıları ve Kazanım Bazlı Performans Özeti</h3>
      <table>
        <thead>
          <tr>
            <th>Gelişim Alanı</th>
            <th>Ders</th>
            <th>Öğrenme Çıktısı / Kazanım</th>
            <th style="text-align:center;">Ortalama</th>
            <th style="text-align:center;">Düzey</th>
          </tr>
        </thead>
        <tbody>{satirlar_html}</tbody>
      </table>

      <div class="yorum-kutusu">
        <strong style="color:#15803d; display:block; margin-bottom:4px;">✍️ Sınıf Öğretmeni Bütüncül Değerlendirmesi:</strong>
        <div>{yorum_blok}</div>
      </div>

      <div class="imza">
        <div>Veli İmzası: ______________________</div>
        <div>Sınıf Öğretmeni: <strong>Ercan DİRİK</strong></div>
      </div>
    </body>
    </html>
    """


# ==================== ANA UYGULAMA ARAYÜZÜ ====================
st.title("📊 2-C Sınıfı Bütüncül Gelişim & Analitik Raporlama Merkezi")

if not SHEET_ID:
    st.error("Streamlit Secrets içinde `SHEET_ID` bulunamadı.")
    st.stop()

try:
    df_kayitlar, ogrenci_listesi = verileri_yukle(SHEET_ID)
except Exception as e:
    st.error(f"Google Sheets verisi yüklenemedi. Hata: {e}")
    st.stop()

# Üst KPI Metrik Bandı
m1, m2, m3, m4 = st.columns(4)
m1.metric("Toplam Kanıt / Gözlem", len(df_kayitlar))
m2.metric("Aktif Öğrenci Sayısı", len(ogrenci_listesi))
m3.metric("Sınıf Genel Ortalaması", f"{df_kayitlar['Puan'].mean():.2f} / 4.00")
kanit_sayisi = (df_kayitlar["Kanit_URL"] != "").sum()
m4.metric("Drive Görsel Kanıt Sayısı", int(kanit_sayisi))

tab1, tab2, tab3 = st.tabs([
    "📈 Sınıf Performans & Müdahale Analizi",
    "🎓 Bireysel Öğrenci Portfolyo Karnesi",
    "🧠 AI Pedagog & Toplu Karne Yorumu"
])

# ==================== SEKME 1: SINIF ANALİZİ & MÜDAHALE RADARI ====================
with tab1:
    c_sol, c_sag = st.columns(2)

    with c_sol:
        st.subheader("Gelişim Alanlarına Göre Sınıf Ortalaması")
        alan_df = df_kayitlar.groupby("Alan", as_index=False)["Puan"].mean().round(2)
        fig_alan = px.bar(
            alan_df, x="Alan", y="Puan", text="Puan", color="Alan",
            range_y=[0, 4.3], color_discrete_sequence=px.colors.qualitative.Set2
        )
        fig_alan.update_traces(textposition="outside")
        fig_alan.update_layout(showlegend=False, height=340, margin=dict(t=20, b=20))
        st.plotly_chart(fig_alan, use_container_width=True)

    with c_sag:
        st.subheader("Ders Bazlı Başarı Dağılımı")
        ders_df = df_kayitlar.groupby("Ders", as_index=False)["Puan"].mean().round(2).sort_values("Puan")
        fig_ders = px.bar(
            ders_df, x="Puan", y="Ders", orientation="h", text="Puan",
            range_x=[0, 4.4], color="Puan", color_continuous_scale="Tealgrn"
        )
        fig_ders.update_traces(textposition="outside")
        fig_ders.update_layout(coloraxis_showscale=False, height=340, margin=dict(t=20, b=20))
        st.plotly_chart(fig_ders, use_container_width=True)

    st.divider()
    st.subheader("🎯 Kazanım (Öğrenme Çıktısı) Bazlı Sınıf Başarı Sıralaması")
    secili_ders_filtre = st.selectbox("Derse Göre Filtrele:", ["Tümü"] + sorted(df_kayitlar["Ders"].unique().tolist()))
    df_filtre = df_kayitlar if secili_ders_filtre == "Tümü" else df_kayitlar[df_kayitlar["Ders"] == secili_ders_filtre]

    hedef_ozet = df_filtre.groupby(["Ders", "Hedef"], as_index=False).agg(
        Ortalama=("Puan", "mean"),
        Kayıt_Sayısı=("Puan", "count")
    ).round(2).sort_values("Ortalama")

    fig_hedef = px.bar(
        hedef_ozet, x="Ortalama", y="Hedef", orientation="h", text="Ortalama",
        color="Ortalama", range_x=[0, 4.4],
        color_continuous_scale=["#ef4444", "#f59e0b", "#10b981"]
    )
    fig_hedef.update_traces(textposition="outside")
    fig_hedef.update_layout(height=max(300, len(hedef_ozet) * 38), coloraxis_showscale=False, margin=dict(t=10, b=10))
    st.plotly_chart(fig_hedef, use_container_width=True)

    st.subheader("🚨 Bireysel Destek (Telafi) İhtiyacı Olan Öğrenciler (Ortalama ≤ 2.25)")
    ogr_hedef_ort = df_kayitlar.groupby(["Ogrenci", "Ders", "Hedef"], as_index=False)["Puan"].mean().round(2)
    destek_df = ogr_hedef_ort[ogr_hedef_ort["Puan"] <= 2.25].sort_values(["Puan", "Ogrenci"])
    if destek_df.empty:
        st.success("🎉 Şu an 2.25 ortalamanın altında kalan kritik bir kazanım kaydı görünmüyor.")
    else:
        st.dataframe(destek_df, use_container_width=True, hide_index=True)

# ==================== SEKME 2: BİREYSEL ÖĞRENCİ PORTFOLYO KARNESİ ====================
with tab2:
    col_sec, col_indir = st.columns([2, 1])
    with col_sec:
        secim_ogr = st.selectbox("Öğrenci Seçin:", ogrenci_listesi, key="tab2_ogr")

    df_tek = df_kayitlar[df_kayitlar["Ogrenci"] == secim_ogr].copy()

    if df_tek.empty:
        st.info(f"**{secim_ogr}** için henüz değerlendirme kaydı bulunmuyor.")
    else:
        # Karne HTML indirme butonu
        kayitli_ai_yorum = st.session_state.get(f"yorum_{secim_ogr}", "")
        karne_html = kurumsal_karne_html_olustur(secim_ogr, df_tek, kayitli_ai_yorum)
        with col_indir:
            st.write("")
            st.download_button(
                label="🖨️ Yazdırılabilir Karne Raporu İndir (HTML/PDF)",
                data=karne_html.encode("utf-8"),
                file_name=f"{secim_ogr.replace(' ', '_')}_Gelisim_Karnesi.html",
                mime="text/html",
                use_container_width=True
            )

        k1, k2, k3 = st.columns(3)
        k1.metric("Genel Ortalama", f"{df_tek['Puan'].mean():.2f} / 4.00")
        k2.metric("Toplam Değerlendirme", f"{len(df_tek)} Kayıt")
        en_guclu_ders = df_tek.groupby("Ders")["Puan"].mean().idxmax()
        k3.metric("En Güçlü Olduğu Alan/Ders", en_guclu_ders)

        g1, g2 = st.columns(2)

        # 1. Gelişim Alanları Radar Grafiği
        with g1:
            st.markdown("**🕸️ Bütüncül Gelişim Alanları Dengesi**")
            radar_df = df_tek.groupby("Alan", as_index=False)["Puan"].mean().round(2)
            fig_radar = go.Figure(data=go.Scatterpolar(
                r=radar_df["Puan"].tolist() + [radar_df["Puan"].iloc[0]],
                theta=radar_df["Alan"].tolist() + [radar_df["Alan"].iloc[0]],
                fill="toself",
                line_color="#7c3aed"
            ))
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 4])),
                showlegend=False, height=340, margin=dict(t=25, b=25)
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        # 2. DOKS Okuma Hızı veya SRSD Yazma Profili Grafiği
        with g2:
            doks_ogr = doks_verisi_cikar(df_tek)
            srsd_ogr = srsd_profili_cikar(df_tek)

            if not doks_ogr.empty:
                st.markdown("**📖 Okuma Akıcılığı (DOKS - Kelime/Dakika) Gelişimi**")
                fig_doks = px.line(
                    doks_ogr, x="Tarih_Kisa", y="DOKS", markers=True, text="DOKS"
                )
                fig_doks.update_traces(textposition="top center", line_color="#059669", marker_size=10)
                fig_doks.update_layout(height=340, margin=dict(t=25, b=25), xaxis_title="Tarih", yaxis_title="Doğru Kelime / Dk")
                st.plotly_chart(fig_doks, use_container_width=True)
            elif not srsd_ogr.empty:
                st.markdown("**✍️ SRSD 4 Boyutlu Yazma Gelişim Profili**")
                fig_srsd = px.bar(
                    srsd_ogr, x="Boyut", y="Puan", text="Puan", color="Boyut", range_y=[0, 4.4]
                )
                fig_srsd.update_traces(textposition="outside")
                fig_srsd.update_layout(showlegend=False, height=340, margin=dict(t=25, b=25))
                st.plotly_chart(fig_srsd, use_container_width=True)
            else:
                st.markdown("**📚 Derslere Göre Performans Ortalaması**")
                d_tek = df_tek.groupby("Ders", as_index=False)["Puan"].mean().round(2)
                fig_d = px.bar(d_tek, x="Ders", y="Puan", text="Puan", range_y=[0, 4.4], color="Ders")
                fig_d.update_traces(textposition="outside")
                fig_d.update_layout(showlegend=False, height=340, margin=dict(t=25, b=25))
                st.plotly_chart(fig_d, use_container_width=True)

        # Eğer hem DOKS hem SRSD varsa SRSD'yi de ayrıca göster
        srsd_ek = srsd_profili_cikar(df_tek)
        if not doks_ogr.empty and not srsd_ek.empty:
            st.markdown("**✍️ SRSD 4 Boyutlu Yazma Gelişim Profili**")
            fig_srsd2 = px.bar(srsd_ek, x="Boyut", y="Puan", text="Puan", color="Boyut", range_y=[0, 4.4])
            fig_srsd2.update_traces(textposition="outside")
            fig_srsd2.update_layout(showlegend=False, height=280, margin=dict(t=15, b=15))
            st.plotly_chart(fig_srsd2, use_container_width=True)

        st.subheader("📂 Öğrenci Süreç Günlüğü & Drive Dijital Portfolyo Kanıtları")
        gosterim_df = df_tek[["Tarih", "Alan", "Ders", "Hedef", "Puan", "Temiz_Not", "Kanit_URL"]].iloc[::-1]
        st.dataframe(
            gosterim_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Kanit_URL": st.column_config.LinkColumn("Drive Kanıtı", display_text="📎 Kâğıdı Aç"),
                "Puan": st.column_config.NumberColumn("Puan (1-4)", format="%d ⭐")
            }
        )

# ==================== SEKME 3: AI PEDAGOG & KARNE YORUMU ====================
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
                            st.success("Yorum üretildi! 2. sekmeden yazdırılabilir karne indirirseniz bu yorum otomatik içine eklenecektir.")
                        except Exception as e:
                            st.error(f"Hata oluştu: {e}")

            mevcut_yorum = st.session_state.get(f"yorum_{secili_ogr}", "")
            guncel_metin = st.text_area("Üretilen Metin (Düzenleyebilirsiniz):", value=mevcut_yorum, height=215)
            if guncel_metin:
                st.session_state[f"yorum_{secili_ogr}"] = guncel_metin

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
                        st.session_state[f"yorum_{ogr}"] = yorum
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
