"""
Kamuflaj - Gizli kelime havuzu.

Havuz "ortalama ustu / zor" seviyede Turkce kelimelerden olusur; kasitli olarak
"masa, sandalye, kalem" gibi kolay kelimeler eklenmemistir. Toplam kelime sayisi
300'un uzerindedir: 4 kisilik bir grup haftada 5 oyun oynasa bile ayni kelimeyi
gormeden aylarca oynayabilir (ayrica her oda son 80 kelimeyi hafizasinda tutar
ve tekrar etmemeye calisir).
"""

from __future__ import annotations

import random
from typing import Iterable, List, Optional

# Turkce'ye duyarli kucuk harf donusumu ("I" -> "i" degil "i"; "I" -> "i")
_TR_LOWER_MAP = str.maketrans({"I": "ı", "İ": "i"})


def tr_lower(text: str) -> str:
    """Turkce karakterleri dogru sekilde kucuk harfe cevirir."""
    return text.translate(_TR_LOWER_MAP).lower()


_RAW_WORDS: List[str] = [
    # --- Mekanik, alet ve makineler ---
    "Sarkaç", "Zemberek", "Mengene", "Kerpeten", "Pergel", "Gönye", "Matkap",
    "Havya", "Perçin", "Rulman", "Krank", "Piston", "Volan", "Türbin", "Dinamo",
    "Jeneratör", "Kompresör", "Vinç", "Dişli", "Zımba", "Tornavida", "Keski",
    "Rende", "Mandal", "Makara", "Kasnak", "Supap", "Karbüratör", "Amortisör",
    "Balata", "Debriyaj", "Radyatör", "Şanzıman", "Pense", "Törpü", "Eğe",
    "Cıvata", "Somun", "Vida", "Kelepçe", "Palet", "Kriko", "Körük", "Kaynak",
    "Çıkrık", "Tezgah", "Torna", "Zincir", "Kama", "Bilyalı yatak",
    # --- Bilim, uzay ve doga ---
    "Plazma", "Fosil", "Meridyen", "Girdap", "Kehribar", "Mercan", "Magma",
    "Buzul", "Kuyrukluyıldız", "Bulutsu", "Asteroit", "Meteor", "Karadelik",
    "Yerçekimi", "Manyetizma", "Elektron", "Molekül", "Enzim", "Kromozom",
    "Fotosentez", "Klorofil", "Antikor", "Hormon", "Nöron", "Kıkırdak",
    "Diyafram", "Omurga", "Mutasyon", "Simbiyoz", "Osmoz", "Yoğuşma",
    "Buharlaşma", "Tortul", "Lav", "Kuvars", "Granit", "Obsidyen", "Liken",
    "Yosun", "Polen", "Kozalak", "Reçine", "Nektar", "Tundra", "Bataklık",
    "Sarkıt", "Dikit", "Vaha", "Kanyon", "Fay hattı", "Gelgit", "Serap",
    "Kutup ışıkları", "Çığ", "Hortum", "Sismik dalga", "Uranyum", "Civa",
    "Grafit", "Alaşım", "Mıknatıs", "Prizma", "Kılcal damar", "Salgı",
    # --- Muzik ve sanat ---
    "Gramofon", "Metronom", "Arp", "Obua", "Fagot", "Klavsen", "Mandolin",
    "Bağlama", "Kanun", "Kaval", "Zurna", "Tulum", "Darbuka", "Senfoni",
    "Koro", "Fresk", "Mozaik", "Heykel", "Gravür", "Vitray", "Tuval", "Şövale",
    "Natürmort", "Minyatür", "Ebru", "Tezhip", "Seramik", "Çömlek", "Porselen",
    "Akort", "Diyapazon", "Viyolonsel", "Kontrbas", "Tef", "Ney", "Rebap",
    "Tambur", "Perde", "Nakarat", "Kemençe", "Orkestra şefi", "Pandomim",
    "Heykeltıraş", "Kabartma", "Hat sanatı", "Oyma",
    # --- Tarih, mitoloji ve savas ---
    "Lahit", "Papirüs", "Hiyeroglif", "Piramit", "Sfenks", "Mumya", "Firavun",
    "Mancınık", "Zırh", "Miğfer", "Kalkan", "Mızrak", "Arbalet", "Hançer",
    "Gladyatör", "Lejyon", "Kervansaray", "Ferman", "Tuğra", "Sancak", "Taht",
    "Sur", "Mazgal", "Hendek", "Zindan", "Sarnıç", "Akropol", "Amfitiyatro",
    "Rasathane", "Tılsım", "Muska", "Kehanet", "Efsane", "Destan", "Totem",
    "Simya", "Kadırga", "Antika", "Kalyon", "Haçlı seferi", "Kabile", "Göçebe",
    "İpek Yolu", "Berat", "Vakıf", "Lonca", "Tımar", "Mühür",
    # --- Yapi ve mekan ---
    "Kubbe", "Minare", "Sütun", "Kemer", "Revak", "Viyadük", "Baraj", "Fener",
    "Hamam", "Kule", "Çeşme", "Tünel", "Teleferik", "Füniküler", "İskele",
    "Payanda", "Kiriş", "Lento", "Baca", "Künk", "Fayans", "Harç", "Mala",
    "Dalgakıran", "Labirent", "Gözetleme kulesi", "Çatı katı", "Bodrum",
    "Su kemeri", "Değirmen", "Ahır", "Kuyu", "Tahterevalli", "Vitrin",
    # --- Denizcilik, ulasim ve kesif ---
    "Pusula", "Dümen", "Çapa", "Yelken", "Halat", "Sal", "Denizaltı",
    "Torpido", "Periskop", "Zeplin", "Planör", "Paraşüt", "Lokomotif", "Vagon",
    "Buzkıran", "Feribot", "Kano", "Duba", "Şamandıra", "Enkaz", "Rota",
    "Kapsül", "Bumerang", "Kızak", "Kürek", "Can yeleği", "Sintine",
    "Makine dairesi", "Mayın", "Deniz feneri", "Karavan", "Füze", "Uydu",
    # --- Teknoloji ve olcum ---
    "Daktilo", "Pikap", "Telgraf", "Mors alfabesi", "Faks", "Projektör",
    "Slayt", "Objektif", "Tripod", "Vizör", "Teleskop", "Mikroskop", "Dürbün",
    "Barometre", "Termometre", "Sismograf", "Jiroskop", "Radar", "Sonar",
    "Anten", "Kondansatör", "Transistör", "Rezistans", "Röle", "Sigorta",
    "Trafo", "Bobin", "Algoritma", "Piksel", "Şifreleme", "Devre kartı",
    "Lehim", "Kablo demeti", "Kumpas", "Mikrofilm", "Hologram", "Lazer",
    "Dijital ikiz", "Yapay zekâ", "Kuantum", "Robot kol", "Güneş paneli",
    # --- Soyut kavramlar ---
    "Nostalgi", "Melankoli", "Kıskançlık", "Tevazu", "Pişmanlık", "Vicdan",
    "Önyargı", "Mahremiyet", "Kader", "Tesadüf", "Adalet", "Sadakat",
    "İhanet", "Şüphe", "İroni", "Metafor", "Paradoks", "Hipotez", "Dogma",
    "Ritüel", "Tabu", "Hayranlık", "Mizah", "Panik", "Merak", "Sabır", "Hırs",
    "Gurur", "Empati", "Sezgi", "Önsezi", "Kabus", "Halüsinasyon", "Hipnoz",
    "Telepati", "Dejavu", "İlham", "Hafıza", "Hezeyan", "Pathos", "Nefs",
    "Özgürlük", "Mahcubiyet", "Çaresizlik", "Cesaret", "Fedakârlık",
    "Kararsızlık", "Takıntı", "Alışkanlık", "Bürokrasi", "Sansür", "Propaganda",
    # --- Oyun, spor ve eglence ---
    "Mikado", "Dart", "Eskrim", "Kriket", "Ragbi", "Halter", "Jimnastik",
    "Okçuluk", "Paten", "Trambolin", "Yoyo", "Uçurtma", "Bilardo", "Langırt",
    "Domino", "Bilye", "Satranç", "Tavla", "Jokey", "Sirk", "Kukla",
    "İllüzyon", "Maskot", "Podyum", "Tombala", "Çember", "Kement", "Yarış pisti",
    # --- Mutfak, bitki ve zanaat ---
    "Safran", "Zerdeçal", "Hindiba", "Sumak", "Pekmez", "Küspe", "Maya",
    "Kuşkonmaz", "Enginar", "Hardal", "Vanilya", "Karanfil", "Tarhun",
    "Mayonez", "Kefir", "Boza", "Turşu", "Salamura", "Kavurma", "Fırın taşı",
    "Havan", "Süzgeç", "Kepçe", "Tandır", "Değirmen taşı", "Pastörizasyon",
    "Fermantasyon", "Reçel", "Baharat", "Zeytinyağı", "Tuzluk", "Cezve",
    "Semaver", "Kürdan", "Kuluçka", "Arı kovanı", "İpek böceği", "Keçe",
    "Dokuma tezgahı", "Dantel", "Nakış", "Kunduracı", "Deri tabaklama",
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
    """
    Havuzdan rastgele bir kelime secer.

    `exclude` icinde verilen (son oynanan) kelimeler atlanir; havuz tukenirse
    kisitlama kaldirilir ve tum havuzdan secim yapilir.
    """
    excluded = {tr_lower(str(item)) for item in (exclude or [])}
    pool = [word for word in WORDS if tr_lower(word) not in excluded]
    if not pool:
        pool = WORDS
    return random.choice(pool)


if __name__ == "__main__":  # hizli dogrulama: python words.py
    print(f"Toplam kelime: {len(WORDS)}")
    print("Ornek 10 kelime:", ", ".join(random.sample(WORDS, 10)))
