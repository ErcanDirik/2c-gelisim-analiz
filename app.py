import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import re
import time

st.set_page_config(page_title="2-C Gelişim Analizi", page_icon="📊", layout="centered")
st.title("📊 2-C Bütüncül Gelişim Analizi")

SHEET_ID = "173-bZAG4XovDG8ZJlXj3CrgV5D7VAAZk83FxLFT0Tj8"
BASE_URL_KAYITLAR = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"
BASE_URL_OGRENCILER = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=Ogrenciler"

def doks_to_puan(doks):
    if pd.isna(doks) or doks <= 0:
        return np.nan
    if doks <= 40:
        return 1
    elif doks <= 60:
        return 2
    elif doks <= 80:
        return 3
    else:
        return 4

def okuma_notu_ayikla(metin):
    if pd.isna(metin):
        return np.nan, np.nan
    s = str(metin).strip()
    if s.lower() in ['', 'nan', 'none']:
        return np.nan, np.nan
        
    doks_m = re.search(r'(\d+)', s)
    yuzde_m = re.search(r'\(\s*%?\s*(\d+(?:[.,]\d+)?)\s*%?\s*\)', s) or re.search(r'%\s*(\d+(?:[.,]\d+)?)', s)
    
    doks = int(doks_m.group(1)) if doks_m else np.nan
    yuzde = float(yuzde_m.group(1).replace(',', '.')) if yuzde_m else np.nan
    return doks, yuzde

@st.cache_data(ttl=15)
def verileri_getir(cache_buster):
    df = pd.read_csv(f"{BASE_URL_KAYITLAR}&cb={cache_buster}", dtype=str)
    df = df.iloc[:, :7]
    df.columns = ['Tarih', 'Ogrenci_Adi', 'Alan', 'Ders', 'Alt_Beceri', 'Puan', 'Not']
    
    df['Ogrenci_Adi'] = df['Ogrenci_Adi'].fillna('').astype(str).str.strip()
    df['Alt_Beceri'] = df['Alt_Beceri'].fillna('').astype(str).str.strip()
    df['Alan'] = df['Alan'].fillna('').astype(str).str.strip()
    df['Ders'] = df['Ders'].fillna('').astype(str).str.strip()
    df['Not'] = df['Not'].fillna('').astype(str).str.strip()
    df['Puan'] = pd.to_numeric(df['Puan'], errors='coerce')
    
    df = df[(df['Ogrenci_Adi'] != '') & (df['Puan'].notna())]
    df = df[~df['Alt_Beceri'].isin(['Xxxyyy', 'nan', ''])]

    doks_list = []
    yuzde_list = []
    for _, r in df.iterrows():
        hedef_kucuk = r['Alt_Beceri'].lower()
        if 'okuma' in hedef_kucuk or 'akıcı' in hedef_kucuk:
            d, y = okuma_notu_ayikla(r['Not'])
            doks_list.append(d)
            yuzde_list.append(y)
        else:
            doks_list.append(np.nan)
            yuzde_list.append(np.nan)

    df['DOKS'] = doks_list
    df['Dogruluk_Yuzde'] = yuzde_list

    df['Puan'] = df.apply(
        lambda r: doks_to_puan(r['DOKS']) if not pd.isna(r['DOKS']) else min(4, max(1, r['Puan'])),
        axis=1
    )

    ogr_df = pd.read_csv(f"{BASE_URL_OGRENCILER}&cb={cache_buster}", header=None, dtype=str)
    sinif = ogr_df[0].dropna().astype(str).str.strip().tolist()
    return df, sinif

if 'cb' not in st.session_state:
    st.session_state.cb = int(time.time())

if st.button("🔄 Verileri Yenile"):
    st.session_state.cb = int(time.time())
    st.cache_data.clear()

df, sinif_listesi = verileri_getir(st.session_state.cb)

tab1, tab2, tab3, tab4 = st.tabs(["👤 Öğrenci & Yorum", "⏱️ DOKS & Doğruluk", "🟩 Matris", "⚠️ Eksik Gözlem"])

# ==================== 1. SEKME: ÖĞRENCİ RADAR + DOKS SEYRİ + e-OKUL YORUMU ====================
with tab1:
    secili_ogr = st.selectbox("Öğrenci Seçin:", sinif_listesi)
    ogr_veri = df[df['Ogrenci_Adi'] == secili_ogr]

    if ogr_veri.empty:
        st.info("Bu öğrenci için henüz kayıt bulunmuyor.")
    else:
        ogr_doks = ogr_veri.dropna(subset=['DOKS'])
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Genel Ortalama", f"{ogr_veri['Puan'].mean():.2f} / 4")
        col2.metric("Toplam Gözlem", f"{len(ogr_veri)}")
        if not ogr_doks.empty:
            son_r = ogr_doks.iloc[-1]
            y_ek = f" (%{int(son_r['Dogruluk_Yuzde'])})" if not pd.isna(son_r['Dogruluk_Yuzde']) else ""
            col3.metric("Son DOKS", f"{int(son_r['DOKS'])}{y_ek}")
        else:
            col3.metric("Son DOKS", "-")

        kategoriler = ['Türkçe', 'Matematik', 'Hayat Bilgisi', 'Duyuşsal', 'Psikomotor']
        degerler = []
        for k in kategoriler:
            if k in ['Duyuşsal', 'Psikomotor']:
                alt = ogr_veri[ogr_veri['Alan'] == k]['Puan']
            else:
                alt = ogr_veri[ogr_veri['Ders'] == k]['Puan']
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

        # DOKS & Doğruluk Gelişim Seyri (1 veya daha fazla ölçüm varsa her zaman göster)
        if not ogr_doks.empty:
            st.subheader("⏱️ DOKS & Doğruluk Gelişim Seyri")
            seyir_adimlari = []
            for _, r in ogr_doks.iterrows():
                y_str = f" (%{int(r['Dogruluk_Yuzde'])})" if not pd.isna(r['Dogruluk_Yuzde']) else ""
                seyir_adimlari.append(f"**{int(r['DOKS'])}{y_str}** `[{str(r['Tarih'])[:10]}]`")
            st.markdown(" → ".join(seyir_adimlari))

            if len(ogr_doks) >= 2:
                fig_ok, ax_ok = plt.subplots(figsize=(6, 2.6), dpi=150)
                ax_ok.plot(range(len(ogr_doks)), ogr_doks['DOKS'].values, marker='o', color='#27ae60', linewidth=2.2)
                for idx, (_, r) in enumerate(ogr_doks.iterrows()):
                    lbl = f"{int(r['DOKS'])} (%{int(r['Dogruluk_Yuzde'])})" if not pd.isna(r['Dogruluk_Yuzde']) else f"{int(r['DOKS'])}"
                    ax_ok.text(idx, r['DOKS'] + 2, lbl, ha='center', fontweight='bold', fontsize=8.5)
                ax_ok.set_xticks(range(len(ogr_doks)))
                ax_ok.set_xticklabels([str(t)[:10] for t in ogr_doks['Tarih']], rotation=20, fontsize=8)
                ax_ok.set_ylim(0, ogr_doks['DOKS'].max() + 18)
                ax_ok.set_ylabel("DOKS")
                ax_ok.grid(True, linestyle=':', alpha=0.6)
                st.pyplot(fig_ok)

        st.subheader("📝 e-Okul Gelişim Raporu Yorum Taslağı")
        hedef_ort = ogr_veri.groupby('Alt_Beceri')['Puan'].mean()
        guclu = [re.sub(r'^T\d+-[A-Z0-9.]+\s*', '', h).lower() for h, p in hedef_ort.items() if p >= 3.5]
        destek = [re.sub(r'^T\d+-[A-Z0-9.]+\s*', '', h).lower() for h, p in hedef_ort.items() if p < 2.5]
        
        doks_cumle = ""
        if not ogr_doks.empty:
            son_satir = ogr_doks.iloc[-1]
            son_doks = int(son_satir['DOKS'])
            yuzde_bilgi = f" (%{int(son_satir['Dogruluk_Yuzde'])} doğruluk oranıyla)" if not pd.isna(son_satir['Dogruluk_Yuzde']) else ""
            doks_cumle = f"Akıcı okuma değerlendirmesinde dakikada {son_doks} doğru kelime okuma{yuzde_bilgi} düzeyine ulaşmıştır. "

        yorum = f"{secili_ogr}, sınıf içi öğrenme süreçlerine katılım göstermektedir. {doks_cumle}"
        if guclu:
            yorum += f"Özellikle {', '.join(guclu[:2])} becerilerinde yüksek düzeyde başarı sergilemiştir. "
        if destek:
            yorum += f"Bununla birlikte {', '.join(destek[:2])} alanlarında düzenli tekrar ve bireysel destekle gelişimini sürdürmesi faydalı olacaktır."
        else:
            yorum += "Gözlemlenen tüm öğrenme çıktılarında istikrarlı ve başarılı bir gelişim grafiği çizmektedir."

        st.text_area("Kopyalayıp e-Okul'a yapıştırabilirsiniz:", yorum, height=110)

# ==================== 2. SEKME: SINIF DOKS & DOĞRULUK SIRALAMASI ====================
with tab2:
    okuma_kayitlari = df.dropna(subset=['DOKS']).copy()
    if okuma_kayitlari.empty:
        st.info("Henüz DOKS verisi girilmemiş.")
    else:
        ozet_list = []
        for ogr, grup in okuma_kayitlari.groupby('Ogrenci_Adi', sort=False):
            ilk = int(grup['DOKS'].iloc[0])
            son = int(grup['DOKS'].iloc[-1])
            son_yuzde = grup['Dogruluk_Yuzde'].iloc[-1]
            duzey = int(doks_to_puan(son))
            
            seyir_parcalari = []
            for _, gr in grup.iterrows():
                if not pd.isna(gr['Dogruluk_Yuzde']):
                    seyir_parcalari.append(f"{int(gr['DOKS'])} (%{int(gr['Dogruluk_Yuzde'])})")
                else:
                    seyir_parcalari.append(f"{int(gr['DOKS'])}")

            ozet_list.append({
                'Öğrenci': ogr,
                'Son DOKS': son,
                'Doğruluk (%)': f"%{int(son_yuzde)}" if not pd.isna(son_yuzde) else "-",
                'Düzey (1-4)': duzey,
                'Fark': son - ilk,
                'Gelişim Seyri': " → ".join(seyir_parcalari)
            })
        
        okuma_ozet_df = pd.DataFrame(ozet_list).sort_values(by='Son DOKS', ascending=True)
        sinif_ort = okuma_ozet_df['Son DOKS'].mean()
        st.metric("Sınıf Güncel DOKS Ortalaması", f"{sinif_ort:.1f} doks")

        fig2, ax2 = plt.subplots(figsize=(8.5, max(4, len(okuma_ozet_df) * 0.48)), dpi=150)
        renk_haritasi = {1: '#e74c3c', 2: '#f39c12', 3: '#3498db', 4: '#27ae60'}
        renkler = [renk_haritasi[d] for d in okuma_ozet_df['Düzey (1-4)']]
        bars = ax2.barh(okuma_ozet_df['Öğrenci'], okuma_ozet_df['Son DOKS'], color=renkler, height=0.6)
        ax2.axvline(sinif_ort, color='#2c3e50', linestyle='--', linewidth=1.5, label=f'Sınıf Ort: {sinif_ort:.1f}')
        
        for bar, (_, row) in zip(bars, okuma_ozet_df.iterrows()):
            w = bar.get_width()
            yuzde_str = f" ({row['Doğruluk (%)']})" if row['Doğruluk (%)'] != "-" else ""
            etiket = f"{int(w)}{yuzde_str} [Düzey {row['Düzey (1-4)']}]"
            ax2.text(w + 1, bar.get_y() + bar.get_height()/2, etiket, va='center', fontsize=8, fontweight='bold')
            
        ax2.set_xlim(0, okuma_ozet_df['Son DOKS'].max() + 38)
        ax2.legend()
        ax2.grid(axis='x', linestyle=':', alpha=0.5)
        st.pyplot(fig2)

        st.dataframe(okuma_ozet_df.sort_values(by='Son DOKS', ascending=False)[['Öğrenci', 'Düzey (1-4)', 'Doğruluk (%)', 'Gelişim Seyri', 'Fark']], use_container_width=True, hide_index=True)

# ==================== 3. SEKME: SINIF ISI HARİTASI ====================
with tab3:
    secili_ders = st.selectbox("Ders Seçin:", ["Türkçe", "Matematik", "Hayat Bilgisi"])
    ders_df = df[df['Ders'] == secili_ders]

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

# ==================== 4. SEKME: EKSİK GÖZLEM & DESTEK İHTİYACI ====================
with tab4:
    st.subheader("🚨 Desteklenmesi Gereken Alanlar (Ort. < 2.0)")
    dusuk_df = df.groupby(['Ogrenci_Adi', 'Ders', 'Alt_Beceri'])['Puan'].mean().reset_index()
    dusuk_df = dusuk_df[dusuk_df['Puan'] < 2.0].sort_values(by='Puan')
    if dusuk_df.empty:
        st.success("Ortalaması 2.0 altında kalan kayıt bulunmuyor.")
    else:
        dusuk_df['Puan'] = dusuk_df['Puan'].round(1)
        st.dataframe(dusuk_df, use_container_width=True, hide_index=True)

    st.subheader("📋 Hiç Gözlem Girilmeyen Öğrenciler")
    kayitli_ogrenciler = set(df['Ogrenci_Adi'].unique())
    eksik_ogrenciler = [o for o in sinif_listesi if o not in kayitli_ogrenciler]
    if eksik_ogrenciler:
        st.warning(", ".join(eksik_ogrenciler))
    else:
        st.success("28 öğrencinin tamamı için en az 1 gözlem kaydı mevcut.")
