"""Kamuflaj - gunluk hayattan gizli kelime havuzu."""

from __future__ import annotations

import random
from typing import Iterable, List, Optional

_TR_LOWER_MAP = str.maketrans({"I": "ı", "İ": "i"})


def tr_lower(text: str) -> str:
    return text.translate(_TR_LOWER_MAP).lower()


_RAW_WORDS: List[str] = [
    # Ev ve esyalar
    "Televizyon", "Buzdolabı", "Çamaşır Makinesi", "Bulaşık Makinesi", "Fırın",
    "Mikrodalga", "Çaydanlık", "Su Isıtıcısı", "Tencere", "Tava", "Tabak",
    "Bardak", "Kupa", "Çatal", "Kaşık", "Bıçak", "Kesme Tahtası", "Peçete",
    "Havlu", "Sabun", "Şampuan", "Diş Macunu", "Diş Fırçası", "Tarak", "Ayna",
    "Perde", "Halı", "Koltuk", "Kanepe", "Yastık", "Yorgan", "Çarşaf",
    "Battaniye", "Dolap", "Çekmece", "Kapı", "Pencere", "Balkon", "Asansör",
    "Merdiven", "Kapı Zili", "Anahtar", "Kilit", "Priz", "Ampul", "Avize",
    "Abajur", "Vantilatör", "Klima", "Kalorifer", "Süpürge", "Paspas",
    "Çöp Kovası", "Çöp Poşeti", "Ütü", "Askı", "Çamaşır Mandalı", "İğne",
    "Makas", "Selobant", "Yapıştırıcı", "Çakmak", "Kibrit", "Mum", "Duvar Saati",
    "Çalar Saat", "Terlik", "Kapı Paspası", "Çiçek Saksısı", "Kumbara",
    "Elektrik Faturası", "Su Sayacı", "Yatak", "Masa", "Sandalye", "Sehpa",
    "Kitaplık", "Puf", "Banyo", "Mutfak", "Salon", "Tuvalet Kağıdı",
    "Çamaşır Suyu", "Bulaşık Süngeri", "Deterjan", "Oklava", "Rende",
    "Konserve Açacağı", "Buzluk", "Fırın Eldiveni", "Tuzluk", "Şekerlik",
    "Cezve", "Termos", "Pipet", "Streç Film", "Alüminyum Folyo",
    # Teknoloji
    "Telefon", "Bilgisayar", "Dizüstü Bilgisayar", "Tablet", "Kulaklık",
    "Şarj Aleti", "Şarj Kablosu", "Powerbank", "Hoparlör", "Klavye", "Fare",
    "Monitör", "Yazıcı", "Tarayıcı", "Fotoğraf Makinesi", "USB Bellek",
    "Hafıza Kartı", "Modem", "Wifi Şifresi", "Uzaktan Kumanda", "Oyun Konsolu",
    "Akıllı Saat", "Selfie Çubuğu", "Ekran Koruyucu", "Telefon Kılıfı",
    "Bluetooth Kulaklık", "Sim Kart", "Robot Süpürge", "Drone",
    "Elektrikli Scooter", "Kablosuz Mouse", "Ekran Parlaklığı", "Pil",
    "Uzatma Kablosu", "Güvenlik Kamerası", "Akıllı Televizyon", "Projeksiyon",
    "Mikrofon", "Web Kamerası", "Oyun Kolu", "Ekran Görüntüsü", "Şifre",
    "Antivirüs", "Fotokopi Makinesi", "Barkod Okuyucu", "Yazar Kasa",
    # Yiyecek ve icecek
    "Ekmek", "Simit", "Poğaça", "Börek", "Pide", "Lahmacun", "Pizza",
    "Hamburger", "Patates Kızartması", "Makarna", "Pilav", "Çorba",
    "Mercimek Çorbası", "Köfte", "Tavuk Döner", "İskender", "Kebap",
    "Balık Ekmek", "Yumurta", "Omlet", "Menemen", "Tost", "Sandviç", "Peynir",
    "Kaşar", "Zeytin", "Reçel", "Bal", "Tereyağı", "Yoğurt", "Ayran", "Süt",
    "Çay", "Türk Kahvesi", "Filtre Kahve", "Limonata", "Kola", "Meyve Suyu",
    "Maden Suyu", "Buz", "Dondurma", "Çikolata", "Bisküvi", "Kurabiye", "Kek",
    "Pasta", "Baklava", "Lokum", "Sakız", "Şeker", "Tuz", "Karabiber",
    "Zeytinyağı", "Salça", "Ketçap", "Mayonez", "Turşu", "Salata", "Domates",
    "Salatalık", "Soğan", "Sarımsak", "Patates", "Havuç", "Biber", "Patlıcan",
    "Kabak", "Marul", "Maydanoz", "Limon", "Elma", "Armut", "Muz", "Portakal",
    "Mandalina", "Karpuz", "Kavun", "Üzüm", "Çilek", "Kiraz", "Şeftali",
    "Kayısı", "Erik", "İncir", "Nar", "Avokado", "Fındık", "Fıstık", "Ceviz",
    "Badem", "Leblebi", "Ayçiçek Çekirdeği", "Patlamış Mısır", "Cips",
    "Kuruyemiş", "Çorba Kaşığı", "Kahvaltı Tabağı", "Pide Ekmeği", "Un",
    "Pirinç", "Bulgur", "Makarna Sosu", "Nutella", "Gofret", "Çikolatalı Süt",
    "Soda", "Buzlu Çay", "Sıcak Çikolata", "Milkshake", "Waffle", "Krep",
    "Mantı", "Dolma", "Sarma", "Zeytinyağlı", "Menü", "Garson", "Hesap Fişi",
    # Giyim ve aksesuar
    "Tişört", "Gömlek", "Pantolon", "Kot Pantolon", "Şort", "Etek", "Elbise",
    "Ceket", "Mont", "Kazak", "Hırka", "Yelek", "Eşofman", "Pijama", "Çorap",
    "Ayakkabı", "Spor Ayakkabı", "Bot", "Sandalet", "Kemer", "Şapka", "Bere",
    "Atkı", "Eldiven", "Kravat", "Gözlük", "Güneş Gözlüğü", "Kol Saati",
    "Yüzük", "Küpe", "Kolye", "Bileklik", "Çanta", "Sırt Çantası", "El Çantası",
    "Cüzdan", "Şemsiye", "Mayo", "Bornoz", "Yağmurluk", "Kaban", "Papyon",
    "Saç Tokası", "Saç Kurutma Makinesi", "Parfüm", "Ruj", "Oje", "Krem",
    "Güneş Kremi", "Tıraş Makinesi", "Deodorant", "Islak Mendil",
    # Ulasim
    "Araba", "Otobüs", "Metro", "Tramvay", "Minibüs", "Dolmuş", "Taksi",
    "Bisiklet", "Motosiklet", "Scooter", "Tren", "Uçak", "Gemi", "Vapur",
    "Feribot", "Kamyon", "Traktör", "Ambulans", "Polis Arabası", "İtfaiye",
    "Otobüs Durağı", "Metro İstasyonu", "Tren Garı", "Havalimanı", "Otopark",
    "Trafik Lambası", "Yaya Geçidi", "Köprü", "Tünel", "Benzin İstasyonu",
    "Lastik", "Direksiyon", "Fren", "Vites", "Emniyet Kemeri", "Ehliyet",
    "Araba Plakası", "Navigasyon", "Yol Haritası", "Bagaj", "Valiz",
    "Uçak Bileti", "Pasaport", "Kemer Tokası", "Araç Muayenesi", "Park Cezası",
    "Trafik Cezası", "Yakıt Deposu", "Silecek", "Far", "Korna", "Araba Anahtarı",
    # Mekanlar
    "Market", "Süpermarket", "Bakkal", "Fırın Dükkanı", "Kasap", "Pazar",
    "Alışveriş Merkezi", "Kafe", "Restoran", "Lokanta", "Pastane", "Kuaför",
    "Berber", "Eczane", "Hastane", "Dişçi", "Okul", "Üniversite", "Kütüphane",
    "Sinema", "Tiyatro", "Müze", "Park", "Bahçe", "Plaj", "Deniz", "Havuz",
    "Otel", "Banka", "ATM", "Postane", "Karakol", "Cami", "Stadyum",
    "Halı Saha", "Spor Salonu", "Oto Yıkama", "Kırtasiye", "Çiçekçi", "Terzi",
    "Oyun Parkı", "Lunapark", "Hayvanat Bahçesi", "Şantiye", "Fabrika", "Ofis",
    "Toplantı Odası", "Asansör Boşluğu", "Balık Pazarı", "Köy", "Şehir",
    "Mahalle", "Sokak", "Cadde", "Apartman", "Site", "Kampüs", "Yurt",
    "Servis Durağı", "Bekleme Salonu", "Kuyruk", "Sahil", "Orman", "Dağ",
    # Okul ve ofis
    "Kalem", "Kurşun Kalem", "Silgi", "Kalemtıraş", "Defter", "Kitap",
    "Cetvel", "Pergel", "Hesap Makinesi", "Zımba", "Ataç", "Dosya",
    "Fotokopi", "Tahta", "Tebeşir", "Beyaz Tahta", "Sınav", "Ödev", "Ders",
    "Teneffüs", "Öğretmen", "Öğrenci", "Diploma", "Not Defteri", "Takvim",
    "Ajanda", "Harita", "Dünya Küresi", "Sunum", "Rapor", "Toplantı",
    "Mesai", "Maaş", "Zam", "Prim", "İzin", "Vardiya", "Mülakat",
    "Özgeçmiş", "İmza", "Kaşe", "Zarf", "Pul", "Kartvizit", "Yazı Masası",
    "Döner Koltuk", "Pano", "Beyaz Kağıt", "Klasör", "Post-it",
    # Gunluk hayat ve kavramlar
    "Doğum Günü", "Düğün", "Tatil", "Piknik", "Alışveriş", "Trafik", "Yağmur",
    "Kar", "Güneş", "Rüzgar", "Bulut", "Gökkuşağı", "Yaz", "Kış", "İlkbahar",
    "Sonbahar", "Sabah", "Akşam", "Gece", "Hafta Sonu", "Pazartesi",
    "Fatura", "Kira", "Kredi Kartı", "Bozuk Para", "Nakit Para", "İndirim",
    "Vergi", "Market Fişi", "Market Listesi", "Randevu", "Uyku", "Rüya",
    "Selfie", "Fotoğraf", "Video", "Film", "Dizi", "Reklam", "Haber",
    "Gazete", "Dergi", "Şarkı", "Müzik", "Konser", "Radyo", "Podcast",
    "Sosyal Medya", "Takipçi", "Beğeni", "Emoji", "Mesaj", "Sesli Arama",
    "Zil Sesi", "Bildirim", "Mobil Uygulama", "İnternet", "Kargo",
    "Online Alışveriş", "Abonelik", "Şifre Sıfırlama", "Alarm", "Geç Kalmak",
    "Yolculuk", "Misafir", "Komşu", "Akraba", "Arkadaş", "Sıra Numarası",
    "Bayram", "Yılbaşı", "Hediye", "Balon", "Konfeti", "Pasta Mumu",
    "Davetiye", "Tebrik Kartı", "Çeyiz", "Nişan", "Mezuniyet",
    # Saglik ve bakim
    "İlaç", "Ağrı Kesici", "Vitamin", "Ateş Ölçer", "Maske", "Dezenfektan",
    "Yara Bandı", "Pamuk", "Aşı", "Grip", "Nezle", "Baş Ağrısı", "Diş Ağrısı",
    "Reçete", "Muayene", "Röntgen", "Tansiyon", "Kan Testi", "Hemşire",
    "Doktor", "Hap", "Şurup", "Serum", "Alçı", "Diyet", "Spor Yapmak",
    "Uyku Düzeni", "Su İçmek", "Vitamin Hapı", "Gözlük Numarası",
    # Hayvanlar
    "Kedi", "Köpek", "Kuş", "Papağan", "Balık", "Akvaryum", "Tavuk", "Horoz",
    "İnek", "Koyun", "Keçi", "At", "Eşek", "Fare", "Sincap", "Kaplumbağa",
    "Tavşan", "Kelebek", "Arı", "Karınca", "Sinek", "Örümcek", "Yılan",
    "Aslan", "Kaplan", "Fil", "Zürafa", "Maymun", "Ayı", "Kurt", "Tilki",
    "Deve", "Penguen", "Yunus", "Köpekbalığı", "Martı", "Güvercin", "Baykuş",
    "Kartal", "Tavus Kuşu", "Hamster", "Kuş Kafesi", "Mama Kabı", "Tasma",
    "Kedi Kumu", "Veteriner", "Kümes", "Ahır", "Balık Yemi",
    # Spor, oyun ve eglence
    "Futbol", "Basketbol", "Voleybol", "Tenis", "Yüzme", "Koşu", "Yoga",
    "Pilates", "Boks", "Güreş", "Masa Tenisi", "Satranç", "Bilardo",
    "Bowling", "Kaykay", "Paten", "Dart", "Okey", "Tavla", "İskambil",
    "Puzzle", "Lego", "Top", "Kale Direği", "Hakem", "Penaltı", "Korner",
    "Taraftar", "Forma", "Krampon", "Antrenman", "Maç", "Kupa", "Madalya",
    "Olimpiyat", "Kamp", "Çadır", "Uyku Tulumu", "Mangal", "Piknik Sepeti",
    "Şişme Bot", "Olta", "Salıncak", "Kaydırak", "Tahterevalli", "Uçurtma",
    "Bilye", "Saklambaç", "Körebe", "Yakan Top", "İp Atlama", "Seksek",
    "Lastik Oyunu", "Mendil Kapmaca", "Kutu Oyunu", "Tombala", "Bingo",
    "Karaoke", "Dans", "Sihirbaz", "Palyaço", "Balon Patlatma", "Atari",
    "Playstation", "Bilgisayar Oyunu", "Çizgi Film", "Masal Kitabı",
    # Bebek, cocuk, ev hayati
    "Bebek Arabası", "Biberon", "Emzik", "Bebek Bezi", "Oyuncak Ayı",
    "Oyuncak Araba", "Bebek Maması", "Mama Sandalyesi", "Çocuk Koltuğu",
    "Beşik", "Battaniye Ucu", "Masa Örtüsü", "Dikiş Makinesi", "Örgü Şişi",
    "Yün Yumağı", "Çamaşır Sepeti", "Askı Ucu", "Ayakkabı Boyası", "Şemsiye Askısı",
    # Diger gunluk nesneler
    "Cüzdan Fotoğrafı", "Kimlik Kartı", "Ehliyet Fotoğrafı", "Öğrenci Kartı",
    "Ulaşım Kartı", "Otobüs Bileti", "Sinema Bileti", "Maç Bileti",
    "Market Arabası", "Alışveriş Poşeti", "Bez Çanta", "Kilitli Poşet",
    "Anahtarlık", "El Feneri", "Pil Bitti", "Saat Pili", "Duvar Takvimi",
    "Fotoğraf Çerçevesi", "Resim Çerçevesi", "Vazo", "Yapay Çiçek",
    "Çiçek Sulama Kabı", "Bahçe Hortumu", "Çim Biçme Makinesi", "Kürek",
    "Tırmık", "Merdiven Basamağı", "Tornavida", "Çekiç", "Çivi", "Vida",
    "Matkap", "Metre", "Boya Fırçası", "Rulo", "Maskeleme Bandı",
]


def _dedupe(raw: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in raw:
        word = (item or "").strip()
        if not word:
            continue
        key = tr_lower(word)
        if key in seen:
            continue
        seen.add(key)
        out.append(word)
    return out


WORDS: List[str] = _dedupe(_RAW_WORDS)


def pick_word(exclude: Optional[Iterable[str]] = None) -> str:
    excluded = {tr_lower(str(item)) for item in (exclude or [])}
    pool = [word for word in WORDS if tr_lower(word) not in excluded]
    if not pool:
        pool = WORDS
    return random.choice(pool)


if __name__ == "__main__":
    print(f"Toplam kelime: {len(WORDS)}")
    print("Ornek:", ", ".join(random.sample(WORDS, 12)))
