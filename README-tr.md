# obilet-mcp 🇹🇷

mcp-name: io.github.mohammad-abbasi-sh/obilet-mcp

Türkiye'nin otobüs & uçak bileti araması **obilet.com** için resmi
olmayan, **salt okunur** MCP sunucusu — otobüs konumlarını arayın, bir
güzergâh + tarih için tüm otobüs seferlerini listeleyin (firma, otobüs
tipi, koltuk, kalkış/varış, süre, TL fiyat, firma puanı, duraklar),
sefer detayını okuyun, fiyat istatistikleri alın ve aynı şehir çifti
için uçuş özetini (uçuş sayısı, min/maks fiyat, havayolları) okuyun.

> Mohammad Abbasi tarafından "Turkey MCP factory" (Sepehr tarzı süreç)
> kapsamında geliştirildi. obilet.com ile bağlantısı yoktur.

## Yapay zekâ ajanları için

MCP istemci yapılandırmanıza ekleyin (stdio):

```json
{
  "mcpServers": {
    "obilet": {
      "command": "uvx",
      "args": ["obilet-mcp"]
    }
  }
}
```

veya yerel çalıştırın: `python -m obilet_mcp.server`
(`mcp<2`, `curl-cffi` gerekir).

## Araçlar

| Araç | Açıklama |
|------|----------|
| `obilet_search_locations` | İsimle konum arama — `query` ("Ankara", "İstanbul"), `kind` ("bus" / "flight"); id, ad, görünen ad ve şehir id'si döndürür (otobüs id'leri sayı, uçuş id'leri "250_0" gibi metin) |
| `obilet_search_bus_journeys` | Bir güzergâh + tarih için otobüs seferleri — `origin_id` / `destination_id` (otobüs konum id'leri, örn. 349 İstanbul Avrupa -> 356 Ankara), `date` "YYYY-MM-DD", `sort` ("price_asc" / "departure" / "duration"), `limit` 1..24; sefer id, firma, otobüs tipi, koltuk, istasyonlar, kalkış/varış, süre, TL fiyat, firma puanı (0-10), duraklar ve toplam adet döndürür |
| `obilet_journey_detail` | Bir seferin tam detayı (`journey_id`): firma, otobüs tipi, koltuk, istasyonlar, kalkış/varış, süre, internet & liste fiyatı (TL), hizmet bedeli, firma puanı, otobüs plakası, peron, açıklama ve her durağın saati |
| `obilet_price_stats` | Bir güzergâh + tarih için fiyat istatistikleri: sefer sayısı, min / medyan / ortalama / maks bilet fiyatı (TL) |
| `obilet_flight_summary` | Bir güzergâh + tarih için uçuş özeti: uçuş sayısı, min/maks fiyat (TL), min/maks süre, ilk/son kalkış, direkt uçuş var mı, IATA kodlu havayolları (tek tek uçuş listesi v1'de YOK) |

Örnek çıktı (`obilet_search_bus_journeys` / İstanbul Avrupa -> Ankara, 2026-11-07):

```json
{"origin_id": 349, "destination_id": 356, "date": "2026-11-07",
 "sort": "price_asc", "total": 421, "count": 2, "journeys": [
  {"journey_id": 1432053091, "partner": "Yükseller Aksaray Birlik",
   "bus_type": "2+1", "total_seats": 41, "available_seats": 36,
   "origin": "Esenler Otogarı", "destination": "Ankara (Aşti) Otogarı",
   "departure": "2026-11-07T07:30:00", "arrival": "2026-11-07T15:30:00",
   "duration": "08:00:00", "price_try": 539.0, "original_price_try": 700.0,
   "price_currency": "TRY", "partner_rating": 8.64, …}, …]}
```

## Nasıl çalışır?

obilet.com bir JSON API sunar ama oturum gerektirir: önce bir HTML
sayfası çekilir (çerezleri `ob_Session` ve `__cf_bm` ayarlar), sonra
POST'lar `X-Requested-With: XMLHttpRequest` ile ve o sayfa Referer
olarak gönderilir. Konumlar: POST /json/duraklar (otobüs) veya
/json/ucak-duraklari (uçuş). Seferler: POST
/json/journeys/{kalkış}-{varış}/{tarih} — tek yanıt güzergâhın tüm
seferlerini içerir. Detay: POST /json/sefer-tam/{seferId}. Aynı sefer
yanıtı flightSummary'yi de taşır. Sıralama istemci tarafındadır (fiyat
/ kalkış / süre). Eşzamansız uçuş uç noktası site tarafında bozuk
(404/500), bu yüzden tek tek uçuş listesi v1 kapsamı dışındadır.
Aktarım kalıcı curl-cffi chrome120 oturumu kullanır; istekler ~0.8 sn
arayla yapılır; her şey salt okunurdur, giriş gerekmez, API anahtarı
gerekmez.

## Kurulum

```bash
uvx obilet-mcp        # doğrudan çalıştır (uv gerekir)
# veya
pip install obilet-mcp
obilet-mcp         # MCP sunucusunu stdio üzerinde başlatır
```

## Testler

```bash
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Çevrimdışı testler kayıtlı örnek sayfalarla çalışır (gerçek sayfalar,
2026-11-06); canlı testler obilet.com'a bağlanır.

## Lisans

MIT — bkz. [LICENSE](LICENSE).
