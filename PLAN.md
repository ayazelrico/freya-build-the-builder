# Freya "Build the Builder" — Plan (v2)

Şimdi: Cumartesi 10 Ekim 18:50 TRT. Final brief'ler **Pazar 20:00 TRT**'de açılıyor, submit **Pazar 23:00 TRT**'de kapanıyor.

## 0. Tek cümlede ne yapıyoruz

Bir **fabrika** yazıyoruz: brief (banka kuralları) + openapi.json girer → Freya'da çalışan telefon ajanı (workflow JSON) çıkar.
Ajanı elle yapmıyoruz, marka/logo yok. Çıktı = Freya'ya yüklenen ve `export_workflow` ile dışa aktarılan JSON.

## 1. Puanlama (neden bu mimari)

- Bir müşteri = 3 koşunun **3'ü de** geçerse 1 puan. Kısmi puan yok.
- Geçmek için: (1) bankanın ledger'ı doğru (outcome/reason, promise tutar+tarih, note, callback, transfer, son tool `close_call`), (2) politika, (3) dürüstlük — (2) ve (3)'ü judge model transcript'ten okur.
- Telefon ajanı sabit ve zayıf bir model (`experimental-5`) üzerinde koşuyor. Kural akıl yürütmesini ona bırakırsak 3/3 tutarlılık gelmez.
- Eşitlikte: toplam promise tutarı → kısa build süresi → erken submit.

**Sonuç:** Kural ne kadar kodla/sabit cümleyle yapılabilirse o kadar iyi. Modelin işi sadece konuşmak.

## 2. Builder mimarisi

```
brief(ler) + openapi.json
   │
   ├─(1) LLM (Claude Opus): brief → SPEC (sabit JSON şema)           builder/extract.py
   │      + 2. geçiş: kapsama kontrolü (her kural spec'te var mı, memo eski kuralı ezdi mi)
   ├─(2) KOD: openapi → tool tanımları (alan adları/enum'lar dosyadan)  builder/tools.py
   ├─(3) KOD: SPEC → workflow JSON (deterministik şablon)              builder/generate.py
   │      - code node'lar: iş günü, tatil, deadline, band, floor, deneme tarihleri
   │      - sabit cümleler (açılış, borç bildirimi, SMS cümlesi, veda) TTS ile
   │      - tool post-hook'ları: her sonuca "what_to_do_next" ekler
   │      - create_promise pre-hook: tarih/tutar kural dışıysa kaydı engeller (güvenlik ağı)
   │      - close_call: değişkenlerle "pişmiş" lifecycle tool (model doldurmaz)
   ├─(4) Freya'ya kaydet (save_workflow, aynı slot → update + publish)
   ├─(5) Kendi kendini test (30 dk bütçe içinde): brief'ten üretilmiş senaryolar
   └─(6) Trace (start/end, her model çağrısı, workflow/agent id, testler) + export
```

Genelleme kuralı: **Public brief'lerden hiçbir değer koda/prompta girmez.** Brief A için elle yazılmış spec yalnızca test fixture'ı.

## 3. Workflow iskeleti (üretilen ajan)

| Node | Tip | Ne yapar |
|---|---|---|
| `setup` | code | `now`'dan bugünü, iş günlerini, callback penceresini hesaplar |
| `opening` | conversation | Sabit açılış + "Am I speaking with…". Kim açtı → yönlendirme |
| `third_party` | conversation | Sebep söylemeden callback alır (`schedule_callback`) |
| `identity` | conversation | Sorular sırayla, `verify_identity`; post-hook ne yapılacağını söyler |
| `load_account` | api_request | `get_account` (model değil motor çağırır) |
| `compute` | code | Ürün bazında: sözlü ürün adı, band, deadline, floor, deneme tarihleri, borç cümlesi |
| `negotiate` | conversation | Borç cümlesi (TTS) + pazarlık; `create_promise`, `transfer_to_agent`, `add_note` |
| `end_*` | code + end_call | Outcome/reason değişkenini yazar, sabit veda cümlesi, kapanış |

## 4. Zaman çizelgesi (TRT)

| Zaman | İş | Çıktı |
|---|---|---|
| Cmt 19:00–20:00 | Kurulum, key'ler, baz skor (base agent) | env.sh, ilk skor |
| Cmt 20:00–22:00 | Elle-yazılmış spec ile **generator v1** + Freya'da ilk koşu | Brief A ≥ 6/10 |
| Cmt 22:00–01:00 | Fail analizi (transcript + route_evaluated), şablonu sağlamlaştır | Brief A ≥ 9/10 |
| Paz 09:00–12:00 | LLM spec çıkarıcı + kapsama kontrolü; Brief B (çoklu ürün) | A+B uçtan uca otomatik |
| Paz 12:00–15:00 | `--reps 3` + `--style` (pieces, corrects, talkative, asks_back, in_words) | Kararlılık |
| Paz 15:00–17:00 | Sahte "gizli" brief'ler (dağınık mail+memo formatı, değişik kurallar, değişik openapi) | Builder çökmeden üretir |
| Paz 17:00–18:00 | Trace, export, README, repo, uçtan uca süre tutarak prova | Submit paketi hazır |
| **Paz 18:00** | **Özellik dondurma.** Sadece crash fix | |
| Paz 20:00–22:00 | Final brief'ler: her biri için builder 1 kez, export, commit | 2 workflow + 2 trace |
| Paz 22:00–22:30 | Submit (erken submit tie-break avantajı) | |

Kapasite: aynı anda 1 simülasyon, 10 case = 3–11 dk. Önce sadece fail eden case'leri `--only` ile koşarız.

## 5. İş bölümü

- **Ayaz:** key'ler, GitHub repo, Freya arayüzünden göz kontrolü, kritik kararlar, submit.
- **Claude (ben):** tüm kod, case analizi, sahte brief'ler, trace, submit paketi.

## 6. Senden lazım olanlar (şimdi)

1. `env.sh` → `FREYA_API_KEY`, `FREYA_BANK_TEAM_KEY` (16+ karakter, hep aynı)
2. `ANTHROPIC_API_KEY` (builder'ın kendi model çağrıları)
3. Boş GitHub repo linki
4. Solo mu, takım mı?

## 7. Riskler

| Risk | Önlem |
|---|---|
| Final brief'te yapısal fark (farklı kimlik alanları, kurumsal müşteri, farklı deadline kuralı) | Spec şemasında esnek tipler + serbest metin "ek kurallar" alanı ilgili node prompt'una girer |
| Zayıf model tool sonrası susuyor | Her tool'a post-hook `what_to_do_next` |
| Boolean routing sessizce bozuluyor | Kod sadece string flag yazar |
| Model tarih/tutar uyduruyor | Code node hesaplar + create_promise pre-hook doğrular |
| Workflow limiti | Hep aynı slot (update+publish) |
| 30 dk build limiti | Self-test bütçeli, zaman aşımında en iyi sürüm kalır |

## 8. Final runbook (Pazar 20:00 TRT)

1. Final brief'leri ve openapi dosyalarını `finals/` klasörüne koy (her brief'in kendi openapi'si).
2. Her brief için **bir kez**, elle hiçbir adım olmadan:
   ```bash
   source env.sh
   python3 build.py finals/<brief-1>.md --openapi finals/<openapi-1>.json --slot final-1
   python3 build.py finals/<brief-2>.md --openapi finals/<openapi-2>.json --slot final-2
   ```
   Çıktılar: `out/final-N.export.workflow.json` (submit edilecek), `traces/final-N-<zaman>.jsonl` (submit edilecek).
3. Çökme olursa: sadece parser/crash düzelt. Final brief'ten **hiçbir değer, kural, isim** koda/prompta girmez. Sonra builder'ı baştan çalıştır.
4. `git add -f out/final-* finals/ && git add traces/final-* && git commit -m "Final builds" && git push` → `git rev-parse HEAD` ile commit hash'ini al.
   (Prova: sahte brief C'de uçtan uca 113 sn, export tur alma ayarlarını içeriyor.)
5. Submit: takım (solo), repo linki, commit hash, iki export dosyası, iki trace.

## 9. Durum (Cmt 21:45)

- A+B ajanı varsayılan stil: 10/13 (kalan 3 fail = tek ürünlü A müşterilerinde Brief B'nin not kuralı).
- Stiller: pieces 10/13, corrects 10/13, asks_back 10/13, in_words 9/13, talkative 7→9/13 (turn wait ayarı).
- Sahte gizli brief'ler (C: dağınık ham materyal, D: farklı yapı) çökmeden, doğru spec'le derleniyor.
