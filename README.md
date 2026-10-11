---
title: Kamuflaj
emoji: 🕵️
colorFrom: green
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Arkadaşlarınla oynanan gerçek zamanlı köstebek bulma oyunu
---

# 🕵️ Kamuflaj (Camouflage)

Tarayıcı üzerinden, dünyanın her yerinden arkadaşlarınla oynanan gerçek zamanlı
**Spyfall / Imposter** tarzı gizli kelime oyunu.

Herkese aynı gizli kelime verilir — biri hariç. O kişi **Kamuflaj**'dır.
Sırayla herkes kelimeyi çağrıştıran **tek bir kelime** söyler, sonra oylama yapılır.

* **Backend:** Python 3.12 · FastAPI · WebSocket · Uvicorn
* **Frontend:** HTML + Vanilla JS + Tailwind CSS (CDN) — mobil uyumlu
* **Kelime havuzu:** 440 adet "ortalama üstü / zor" Türkçe kelime
* **Durum:** Tamamen bellekte (veritabanı gerekmez)

---

## Hızlı başlangıç (yerel)

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Sonra `http://localhost:8000` adresini aç. Aynı ağdaki telefonundan da
`http://<bilgisayarının-ip-adresi>:8000` ile girebilirsin.

Alternatif: `python main.py` (aynı sunucuyu başlatır, `PORT` ortam değişkenini okur).

## Docker ile

```bash
docker build -t kamuflaj .
docker run -p 7860:7860 kamuflaj
```

## İnternete açma

### Hugging Face Spaces — Docker (önerilen: tamamen ücretsiz, kredi kartı istemez)

**Otomatik yol — `deploy.py` (önerilen):**
```bash
pip install huggingface_hub
python deploy.py --dry-run     # ne yükleneceğini göster (opsiyonel)
python deploy.py               # Space'i oluşturur, dosyaları push eder, build'i bekler
```
Token: huggingface.co → Settings → Access Tokens → **Write**. Script token'ı
sorar ve istersen `.hf_token` dosyasına kaydeder (bu dosya yüklenmez).
Sonraki güncellemeler için tek komut yeterli: `python deploy.py`

**Elle yol:** huggingface.co → **New Space** → SDK: **Docker** → Template: **Blank**
→ Hardware: **CPU basic (free)** → **Public** → **Files** sekmesinden tüm dosyaları
yükle (`.venv` ve `__pycache__` hariç).

Her iki yolda da `README.md` dosyasının en üstündeki YAML bloğu Space ayarlarını
(`sdk: docker`, `app_port: 7860`) belirler — **silme**. Build bitince site
`https://<kullanıcı-adı>-<space-adı>.hf.space` adresinde açılır. Hiç uykuya
geçmemesi için cron-job.org gibi ücretsiz bir servisle `https://<adres>/healthz`
adresine 10 dakikada bir istek attır.

### Koyeb / Render / Railway / Fly.io
Repoyu bağla; `Dockerfile` otomatik algılanır. Platformun verdiği `PORT`
ortam değişkeni kullanılır, ek ayar gerekmez. (Render'ın ücretsiz planı
15 dakika hareketsizlikte uykuya geçer.)

### Heroku tarzı platformlar
`Procfile` hazır: `web: uvicorn main:app --host 0.0.0.0 --port $PORT ...`

> **Not:** Ters proxy arkasında WebSocket'in çalışması için `--proxy-headers`
> parametresi tüm başlatma komutlarına eklenmiştir.

---

## Oyun kuralları

1. **3–12 oyuncu** aynı odaya girer (4 haneli oda kodu veya davet linki ile).
2. Oda sahibi oyunu başlatır. Sistem rastgele 1 kişiyi **Kamuflaj** seçer,
   diğerlerine havuzdan rastgele seçilmiş **aynı gizli kelimeyi** gösterir.
3. Tur tabanlı: ekranda kimin sırası olduğu yazar. Sırası gelen oyuncu **tek bir
   kelime** yazar; kelimeler herkesin ekranında listelenir.
   * Aynı kelime bir oyunda **iki kez** kullanılamaz.
   * Gizli kelimenin kendisi yazılamaz.
   * Sadece harf, 2–24 karakter.
4. Kişi başı kelime sayısı (1–4, varsayılan 2) dolunca **oylama** açılır.
   Herkes köstebek sandığı kişiye oy verir (kendine oy verilemez, oy değiştirilebilir).
5. Tüm oylar gelince Kamuflaj'ın **45 saniyelik tek tahmin hakkı** başlar.
   * Kamuflaj kelimeyi doğru tahmin ederse — yakalansa bile — **Kamuflaj kazanır**.
   * Aksi halde çoğunluk Kamuflaj'ı doğru bulduysa **Dedektifler** kazanır,
     bulamadıysa yine Kamuflaj kazanır.

### Puanlama
| Durum | Puan |
|---|---|
| Dedektifler kazanır | her dedektif **+2** |
| Kamuflaj kazanır (tahmin yanlış/yok) | Kamuflaj **+2** |
| Kamuflaj doğru tahmin eder | Kamuflaj **+3** |
| Kamuflaj kazansa bile onu doğru oylayan dedektif | **+1** |

Puanlar oda yaşadığı sürece birikir; "Yeni Oyun" ile skor tablosu korunur.

---

## Dosya yapısı

```
main.py              FastAPI uygulaması, WebSocket protokolü, oda & oyun motoru
words.py             440 kelimelik zorlu Türkçe havuz + rastgele seçici
templates/index.html Arayüz (Tailwind CDN, mobil uyumlu, koyu tema)
static/app.js        WebSocket istemcisi ve tüm UI çizimleri
requirements.txt     Python bağımlılıkları
Dockerfile           Üretim imajı
render.yaml          Render.com blueprint
Procfile             Heroku tarzı platformlar
```

## Dayanıklılık özellikleri

* **Yeniden bağlanma:** `player_id` + `token` tarayıcıda saklanır. Sayfa yenilense
  veya mobil ağ kopsa bile oyuncu aynı role ve odaya geri döner.
* **Kopan oyuncu:** sırası otomatik atlanır, oylamada sayılmaz. Oyuncu sayısı
  2'nin altına düşerse oyun güvenli şekilde lobiye döner.
* **Köstebek koparsa** tahmin hakkı kullanılmaz ve oyun otomatik sonuçlanır.
* **Oda sahibi çıkarsa** yetki otomatik olarak başka bir bağlı oyuncuya geçer.
* **Oyun ortasında katılanlar** o eli izleyici olarak görür, sonraki ele dahil olur.
* **Oda sahibi yetkileri:** AFK oyuncunun sırasını atlama, oylamaya erken geçme,
  oyuncu atma, tur sayısını değiştirme.
* Boş odalar 30 dakika sonra otomatik silinir; mesaj hız sınırı ve girdi
  doğrulaması sunucu tarafında uygulanır.
* Köstebeğin kimliği ve gizli kelime, oyun bitmeden **hiçbir** istemciye gönderilmez.

## Sağlık kontrolü

```
GET /healthz          -> {"status":"ok","rooms":N,"players":N,"words":440}
GET /api/room/{kod}   -> oda var mı, hangi fazda, kaç oyuncu
```
