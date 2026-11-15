import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import re

# Sayfa Ayarları (Mobil Uyumlu)
st.set_page_config(page_title="2-C Gelişim Analizi", page_icon="📊", layout="centered")

st.title("📊 2-C Bütüncül Gelişim Analizi")

SHEET_ID = "173-bZAG4XovDG8ZJlXj3CrgV5D7VAAZk83FxLFT0Tj8"
URL_KAYITLAR = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Kayitlar"
URL_OGRENCILER = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Ogrenciler"

@st.cache_data(ttl=60)
def verileri_getir():
    df = pd.read_csv(URL_KAYITLAR)
    df.columns = ['Tarih', 'Ogrenci_Adi', 'Alan', 'Ders', 'Alt_Beceri', 'Puan', 'Not']
    df['Ogrenci_Adi'] = df['Ogrenci_Adi'].astype(str).str.strip()
    df['Alt_Beceri'] = df['Alt_Beceri'].astype(str).str.strip()
    df['Puan'] = pd.to_numeric(df['Puan'], errors='coerce')
    
    df = df.dropna(subset=['Ogrenci_Adi', 'Puan'])
    df = df[~df['Alt_Beceri'].isin(['Xxxyyy', 'nan', ''])]
    df['Puan'] = df['Puan'].clip(1, 4)

    def dkk_bul(metin):
        eslesme = re.search(r'\d+', str(metin))
        return int(eslesme.group()) if eslesme else np.nan

    df['DKK'] = df.apply(
        lambda r: dkk_bul(r['Not']) if ('okuma' in r['Alt_Beceri'].lower() or 'akıcı' in r['Alt_Beceri'].lower()) else np.nan,
        axis=1
    )

    ogr_df = pd.read_csv(URL_OGRENCILER, header=None)
    sinif = ogr_df[0].dropna().astype(str).str.strip().tolist()
    return df, sinif

if st.button("🔄 Verileri Yenile"):
    st.cache_data.clear()

df, sinif_listesi = verileri_getir()

tab1, tab2, tab3 = st.tabs(["👤 Öğrenci Profili", "⏱️ Okuma Hızı (DKK)", "🟩 Sınıf Matrisi"])

# ==================== 1. SEKME: ÖĞRENCİ RADAR + OKUMA GELİŞİM ÇİZGİSİ ====================
with tab1:
    secili_ogr = st.selectbox("Öğrenci Seçin:", sinif_listesi)
    ogr_veri = df[df['Ogrenci_Adi'] == secili_ogr]

    if ogr_veri.empty:
        st.info("Bu öğrenci için henüz kayıt bulunmuyor.")
    else:
        col1, col2 = st.columns(2)
        col1.metric("Genel Ortalama", f"{ogr_veri['Puan'].mean():.2f} / 4")
        col2.metric("Toplam Gözlem", f"{len(ogr_veri)} kayıt")

        kategoriler = ['Türkçe', 'Matematik', 'Hayat Bilgisi', 'Duyuşsal', 'Psikomotor']
        degerler = []
        for k in kategoriler:
            if k in ['Duyuşsal', 'Psikomotor']:
                alt = ogr_veri[ogr_veri['Alan'].str.strip() == k]['Puan']
            else:
                alt = ogr_veri[ogr_veri['Ders'].str.strip() == k]['Puan']
            degerler.append(alt.mean() if not alt.empty else 0)

        degerler_kapali = degerler + [degerler[0]]
        acilar = np.linspace(0, 2 * np.pi, len(kategoriler), endpoint=False).tolist() + [0]

        fig, ax = plt.subplots(figsize=(5, 5), subplot_kw=dict(polar=True), dpi=150)
        ax.fill(acilar, degerler_kapali, color='#2980b9', alpha=0.25)
        ax.plot(acilar, degerler_kapali, color='#2980b9', linewidth=2.2, marker='o')
        ax.set_xticks(acilar[:-1])
        ax.set_xticklabels(kategoriler, fontsize=9, fontweight='bold')
        ax.set_ylim(0, 4)
        ax.set_yticks([1, 2, 3, 4])
        ax.set_yticklabels(['1', '2', '3', '4'], fontsize=8)
        ax.set_title(f"{secili_ogr}\nBütüncül Gelişim Profili", fontsize=11, fontweight='bold', pad=15)
        st.pyplot(fig)

        # Öğrencinin birden fazla okuma akıcılığı ölçümü varsa gelişim grafiği çiz
        ogr_okuma = ogr_veri.dropna(subset=['DKK']).copy()
        if not ogr_okuma.empty:
            st.subheader("⏱️ Okuma Akıcılığı Seyri (DKK)")
            if len(ogr_okuma) >= 2:
                fig_ok, ax_ok = plt.subplots(figsize=(6, 2.8), dpi=150)
                tarih_etiketleri = [str(t)[:10] for t in ogr_okuma['Tarih']]
                ax_ok.plot(range(len(ogr_okuma)), ogr_okuma['DKK'].values, marker='o', color='#27ae60', linewidth=2.2)
                for idx, val in enumerate(ogr_okuma['DKK'].values):
                    ax_ok.text(idx, val + 2, f"{int(val)}", ha='center', fontweight='bold', fontsize=9)
                ax_ok.set_xticks(range(len(ogr_okuma)))
                ax_ok.set_xticklabels(tarih_etiketleri, rotation=20, fontsize=8)
                ax_ok.set_ylim(0, ogr_okuma['DKK'].max() + 18)
                ax_ok.set_ylabel("Kelime / Dk")
                ax_ok.grid(True, linestyle=':', alpha=0.6)
                st.pyplot(fig_ok)
            else:
                st.info(f"Tek ölçüm mevcut: **{int(ogr_okuma['DKK'].iloc[0])} kelime/dakika** ({str(ogr_okuma['Tarih'].iloc[0])[:10]})")

        st.subheader("Hedef Bazlı Puanlar")
        ozet_tablo = ogr_veri.groupby(['Ders', 'Alt_Beceri'])['Puan'].mean().round(1).reset_index()
        ozet_tablo.columns = ['Ders', 'Öğrenme Çıktısı', 'Ortalama']
        st.dataframe(ozet_tablo, use_container_width=True, hide_index=True)

# ==================== 2. SEKME: SINIF OKUMA HIZI VE GELİŞİM RAPORU ====================
with tab2:
    okuma_kayitlari = df.dropna(subset=['DKK']).copy()
    if okuma_kayitlari.empty:
        st.info("Henüz okuma hızı (DKK) verisi girilmemiş.")
    else:
        # Her öğrenci için İlk, Son, Ölçüm Sayısı ve Fark hesapla
        ozet_list = []
        for ogr, grup in okuma_kayitlari.groupby('Ogrenci_Adi'):
            ilk = int(grup['DKK'].iloc[0])
            son = int(grup['DKK'].iloc[-1])
            sayi = len(grup)
            fark = son - ilk
            gecmis = " → ".join([str(int(x)) for x in grup['DKK'].tolist()])
            ozet_list.append({
                'Öğrenci': ogr,
                'İlk': ilk,
                'Son': son,
                'Fark': fark,
                'Ölçüm': sayi,
                'Gelişim Seyri (DKK)': gecmis
            })
        
        okuma_ozet_df = pd.DataFrame(ozet_list).sort_values(by='Son', ascending=True)
        sinif_ort = okuma_ozet_df['Son'].mean()
        st.metric("Sınıf Güncel Okuma Ortalaması", f"{sinif_ort:.1f} kelime/dk")

        fig2, ax2 = plt.subplots(figsize=(8.5, max(4, len(okuma_ozet_df) * 0.48)), dpi=150)
        renkler = ['#27ae60' if v >= sinif_ort else '#e67e22' for v in okuma_ozet_df['Son']]
        bars = ax2.barh(okuma_ozet_df['Öğrenci'], okuma_ozet_df['Son'], color=renkler, height=0.6)
        ax2.axvline(sinif_ort, color='#c0392b', linestyle='--', linewidth=1.6, label=f'Ortalama: {sinif_ort:.1f}')
        
        for bar, (_, row) in zip(bars, okuma_ozet_df.iterrows()):
            w = bar.get_width()
            if row['Ölçüm'] > 1:
                isaret = "+" if row['Fark'] >= 0 else ""
                etiket = f"{int(w)} ({isaret}{row['Fark']})"
            else:
                etiket = f"{int(w)}"
            ax2.text(w + 1, bar.get_y() + bar.get_height()/2, etiket, va='center', fontsize=8.5, fontweight='bold')
            
        ax2.set_xlabel("Güncel Kelime / Dakika (Parantez içi: İlk ölçüme göre değişim)")
        ax2.set_xlim(0, okuma_ozet_df['Son'].max() + 22)
        ax2.legend()
        ax2.grid(axis='x', linestyle=':', alpha=0.5)
        st.pyplot(fig2)

        st.subheader("Tüm Okuma Ölçümleri Geçmişi")
        tablo_gosterim = okuma_ozet_df.sort_values(by='Son', ascending=False)[['Öğrenci', 'Ölçüm', 'Gelişim Seyri (DKK)', 'Fark']]
        st.dataframe(tablo_gosterim, use_container_width=True, hide_index=True)

# ==================== 3. SEKME: SINIF ISI HARİTASI ====================
with tab3:
    secili_ders = st.selectbox("Ders Seçin:", ["Türkçe", "Matematik", "Hayat Bilgisi"])
    ders_df = df[df['Ders'].str.strip() == secili_ders]

    if ders_df.empty:
        st.info(f"{secili_ders} dersi için henüz kayıt girilmemiş.")
    else:
        pivot = ders_df.pivot_table(index='Ogrenci_Adi', columns='Alt_Beceri', values='Puan', aggfunc='mean').reindex(sinif_listesi)
        kisa_sutunlar = [c.split('.')[0] if c.startswith('T') else c[:14] for c in pivot.columns]

        fig3, ax3 = plt.subplots(figsize=(max(6, len(kisa_sutunlar) * 1.3), 9), dpi=150)
        im = ax3.imshow(pivot.values, cmap='RdYlGn', vmin=1, vmax=4, aspect='auto')
        ax3.set_xticks(np.arange(len(kisa_sutunlar)))
        ax3.set_yticks(np.arange(len(sinif_listesi)))
        ax3.set_xticklabels(kisa_sutunlar, fontweight='bold', fontsize=8.5)
        ax3.set_yticklabels(sinif_listesi, fontsize=8)

        for i in range(len(sinif_listesi)):
            for j in range(len(kisa_sutunlar)):
                val = pivot.values[i, j]
                metin = f"{val:.1f}" if not np.isnan(val) else "-"
                ax3.text(j, i, metin, ha="center", va="center", color="black", fontsize=7.5, fontweight='bold')

        plt.colorbar(im, shrink=0.5, label="Düzey (1-4)")
        ax3.set_title(f"2-C {secili_ders} Başarı Matrisi", fontweight='bold')
        st.pyplot(fig3)
