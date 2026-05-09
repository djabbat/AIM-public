# Email-черновик — Giorgi Tsomaia
## Тема: AIM როგორც FCLC-ის ფაქტობრივი იმპლემენტაცია grant-ამდე
## Дата: 2026-05-04 · Канал: Google Chat (НЕ Telegram)
## Статус: DRAFT — на ревью перед отправкой

---

გამარჯობა, გიორგი!

გინდა შემოგთავაზო კონკრეტული ნაბიჯი, რომელიც შეიძლება გავხადოთ FCLC-ის
დღევანდელ მდგომარეობაში — სანამ EIC-ის grant-ი დადასტურდება და სანამ
პარტნიორი კლინიკები მოგვცემდნენ მონაცემებზე წვდომას.

**მოკლე პოზიცია.** AIM-ის ახალი ქვე-სისტემა, **AIM Hive** (`hive.longevity.ge`),
უკვე უზრუნველყოფს იმავე არქიტექტურის მინიმალურ-სიცოცხლისუნარიან ვერსიას,
რომელიც FCLC-ში გვინდა რომ გვქონდეს:

- **Workers (bees)** მუშაობენ ლოკალურად ექიმის ან კლინიკის მანქანაზე;
 ნედლი მონაცემები მანქანის გარეთ არ გადის.
- **Queen** აგრეგირებს მხოლოდ ანონიმიზებულ სიგნალებს (აგრეგირებული
 მრიცხველები, hashed prompt-ფინგერპრინტი, თემების კატეგორიული labels) —
 PII (ელფოსტა, ტელეფონი, file path, სახელი, PMID/DOI) ბლოკდება
 scrubber-ით **ტრანსმისიამდე**.
- **Eval-gate**: ნებისმიერი update, რომელსაც queen აქვეყნებს, გადის
 signature integrity check + ლოკალურ რე-ევალუაციას worker-ზე
 installation-ამდე.

ეს არის სამი კონტრაქტი — **L_PRIVACY**, **L_CONSENT**,
**L_VERIFIABILITY** — რომლებიც FCLC v6.2-ის მიზნების ფუნქციონალურად
შესაბამისია, თუმცა ზუსტი კრიპტოგრაფიული პრიმიტივები განსხვავდება.

### AIM Hive vs FCLC канон — რა ფარავს, რა არ ფარავს

| FCLC primitive | AIM Hive (today) | სტატუსი |
|---|---|---|
| Differential privacy ε-budget | ✅ `aim-dp` crate (Rényi-style linear composition) | ღია |
| Anonymous worker ID (salted hash) | ✅ `aim-hive-worker` | ღია |
| Eval-gated updates | ✅ `aim-hive-queen` distill + signature | ღია |
| L_CONSENT opt-out | ✅ `aim-hive-consumer` (per-kind glob patterns) | ღია |
| **SecAgg+** (Bonawitz secure aggregation) | ❌ TODO (გრაფიკი — `MIGRATION_RUST_PHOENIX.md` Phase 2) | **არ არის** |
| **Krum** Byzantine-robust aggregation | ❌ TODO | **არ არის** |
| Rényi-DP (Mironov 2017) tight composition | ⚠ basic linear composition, RDP გადასასვლელია | ნაწილობრივ |
| FHIR/OMOP adapter | ❌ AIM-ი არ მუშაობს ნედლ EHR-ით | ❌ scope-ის გარეთ |

ე.ი. AIM Hive **არ ცვლის FCLC-ს** — ის არის "MVP" იმავე აზრობრივი
არქიტექტურის, რომელიც ჩვენ შეგვიძლია მოვხმაროთ:

1. **EIC application-ში** — როგორც "uplift target" დამადასტურებელი.
 "ჩვენ უკვე გვაქვს minimal federated worker-queen system; გრანტი
 სჭირდება მის SecAgg+/Krum/Rényi-DP გასაკეთებლად full-clinic-grade-ად."
2. **გრანტამდე ცდისთვის** — შემიძლია ჩაგისვა AIM Hive ლოკალურად შენი
 მანქანაზე, რომ შენ პრაქტიკაში ნახე workflow-ი (ყოველდღიური
 diagnostic ledger, regression detection, health score), პრობლემები
 ადრე გავიხილოთ.

### კონკრეტული თხოვნა

**1. დააინსტალიე native AIM node შენს მანქანაზე.**

```bash
# Linux/macOS
curl -L -o aim.tar.gz https://github.com/djabbat/AIM-public/releases/latest/download/aim-0.1.0-linux.tar.gz
tar -xzf aim.tar.gz
cd aim-0.1.0-linux
bash scripts/install_node.sh

# Windows (PowerShell)
Invoke-WebRequest -Uri https://github.com/djabbat/AIM-public/releases/latest/download/aim-0.1.0-windows.zip -OutFile aim.zip
Expand-Archive aim.zip
cd aim-0.1.0-windows
powershell -ExecutionPolicy Bypass -File scripts\install_node.ps1
```

**2. შეუერთდი Hive-ს (opt-in).**

```bash
echo 'AIM_HIVE_QUEEN_URL=https://hive.longevity.ge' >> ~/.aim_env
aim diag --hive-preview # dry-run, ნედლი აღარაფერი არ გაიგზავნება
aim diag --hive-status
```

**3. ტესტირება განვითარების პროცესში.**

ვმუშაობ Rust + Phoenix-ზე (per `STACK.md`); ყოველი ცვლილება გახდება
release-ი GitHub-ზე. გთხოვ, განახლე ლოკალური node ყოველ ახალ release-ზე
(commands ზემოთ) და გამიგზავნე უკან:

- რას ვერ ხედავ თქვენს მონიტორზე? (UI bug, missing data)
- რომელი workflow-ი არ მუშაობს? (`aim diag --morning`,
 `aim diag --regress`, `aim diag --gen-cases`..)
- რომელი language-ში გამოვიდა Phoenix UI? (იწყება 7 ენით —
 UN-6 + ქართული; გადამოწმე ქართული რენდერინგი arabic ფონტებზე
 არ ეფარება)
- რა გჭირდება, რომ გადახედო რეალური სცენარი (anemia კოჰორტა,
 centriole ინდიკატორების trend, etc.)?

**4. სხდომა.**

თუ გინდა, ვიდეო-სხდომა Saturday 15:00 — ვაჩვენო AIM Hive workflow
ცოცხლად. შენი mentee-ც (ი. ჟელეზნოვი) შეიძლება შეუერთდეს — HSC-სიმულატორი
რომ აშენებს, AIM-ში სუფთა "skill" გახდება.

---

**P.S.** Google Chat-ი არის ჩვენი არჩევანი (Telegram-ი არა, per
`contact_tsomaia.md`). Тут ვუპასუხებ ნებისმიერი დროს.

გმადლობ,
ჯაბა

---

## Сопроводительные ссылки (для самого Jaba перед отправкой)

- AIM v0.1.0 release (private): https://github.com/djabbat/AIM/releases/tag/v0.1.0
- AIM v0.1.0 release (public): https://github.com/djabbat/AIM-public/releases/tag/v0.1.0
- Hive landing: https://hive.longevity.ge
- Migration plan: `~/Desktop/LongevityCommon/AIM/MIGRATION_RUST_PHOENIX.md`
- Stack rule: `~/Desktop/LongevityCommon/AIM/STACK.md`
- FCLC-borrow plan: `~/Desktop/LongevityCommon/AIM/AI/FCLC_BORROW.md`
- Contact memory: `~/.claude/projects/-home-oem/memory/contact_tsomaia.md`

## Перед отправкой проверить
- [ ] Грузинский — попросить ChatGPT-ω/native speaker review (Tsomaia
 грузинский native, плохой грузинский = плохой message)
- [ ] Release URL public/private — подтвердить, что public action ссылка
 ведёт на реальный release
- [ ] AIM 0.1.0 install_node.sh — проверить, что smoke-test проходит на
 чистой Ubuntu/macOS
- [ ] Subject line — чтобы Tsomaia сразу понимал, что это о FCLC-практической-имплементации, а не "посмотри на AI"
