# Przewodnik integracji webhooka SIS w Libli

Libli może wysyłać sfinalizowane wyniki quizów do Twojego systemu informacji
o uczniach (SIS) lub e-dziennika przez webhook HTTP. Ten przewodnik zawiera
wszystko, czego programista potrzebuje, aby zbudować **odbierający** punkt
końcowy.

## Przegląd

- Libli wysyła webhook, gdy wynik quizu ucznia zostaje **sfinalizowany**.
- Jedno zdarzenie jest wysyłane dla każdej kombinacji **(uczeń, kurs, grupa,
  jednostka)**. Uczeń należący do kilku grup w kursie otrzymuje **jedno
  zdarzenie na grupę** (ładunki są identyczne z wyjątkiem bloku `group`). Uczeń
  bez grupy otrzymuje pojedyncze zdarzenie z `"group": null`.
- Dostarczanie jest **asynchroniczne** — sterowane okresowym opróżnianiem
  w tle, więc spodziewaj się zdarzenia wkrótce po finalizacji, a nie w czasie
  rzeczywistym.

## Transport

- **POST** HTTP na adres URL punktu końcowego skonfigurowany przez
  administratora platformy Libli.
- `Content-Type: application/json`.
- **Używaj HTTPS.** Podpis (poniżej) potwierdza integralność i autentyczność,
  ale **nie** szyfruje — przez zwykłe `http` oceny są przesyłane otwartym
  tekstem.

## Nagłówki

| Nagłówek | Wartość |
|---|---|
| `X-Libli-Event` | `result_finalized` |
| `X-Libli-Delivery` | Identyfikator dostawy (liczba całkowita, jako ciąg znaków). Dla zdarzeń **testowych** jest to dosłownie `test`. |
| `X-Libli-Signature` | `sha256=<hex>` — HMAC-SHA256 surowego ciała żądania (zobacz *Weryfikacja podpisu*). |

## Ładunek

**Prawdziwa** dostawa wygląda tak (wariant z wypełnioną grupą; uczeń bez grupy
wysyła ten sam kształt z `"group": null`):

```json
{
  "event": "result_finalized",
  "finalized_at": "2026-07-06T10:15:30.482170+00:00",
  "student": { "external_id": "S-2024-0912", "email": "ada.k@example.edu", "name": "Ada Kowalska" },
  "course":  { "external_id": "MATH-101", "slug": "algebra-i", "title": "Algebra I" },
  "group":   { "id": 42, "external_id": "3B", "name": "Class 3B" },
  "unit":    { "id": 318, "title": "Quadratic Equations" },
  "score":   { "earned": "8.00", "max": "10.00", "percent": 80.0 }
}
```

Uwagi o polach — czytaj uważnie; to tutaj integracje zwykle się mylą:

- **Tożsamość ucznia.** Blok `student` **nie ma numerycznego id**. Jedynym
  kluczem ucznia jest `external_id`. Zarówno `student.external_id`, jak
  i `student.email` **mogą być pustymi ciągami**; `name` służy tylko do
  wyświetlania i nie jest ani unikalne, ani stabilne. Synchronizacja ocen jest
  użyteczna tylko wtedy, gdy `external_id` jest wypełnione — zobacz
  *Idempotentność i korekty*, aby poznać regułę odbiorcy.
- **Oceny są ciągami znaków.** `score.earned` i `score.max` to dziesiętne
  **ciągi** z 2 miejscami po przecinku (np. `"8.00"`). Parsuj je jako dokładne
  liczby dziesiętne, nie zmiennoprzecinkowe.
- **`score.percent` różni się typem.** Zwykle jest to **liczba
  zmiennoprzecinkowa** z 2 miejscami (np. `80.0`, `66.67`), ale jest **liczbą
  całkowitą `0`** w JSON, gdy `max` wynosi 0. Parsuj jako ogólną liczbę.
  Przykładowy blok wyniku dla zerowego max:
  `"score": { "earned": "0.00", "max": "0.00", "percent": 0 }`.
- **`group`.** `null` lub obiekt; `group.external_id` może być puste. Stabilnym
  kluczem grupy jest numeryczne **`group.id`**.
- **`course.external_id`** jest zawsze obecne (Libli wysyła zdarzenia tylko dla
  kursów, które je mają). `unit.id` i `group.id` to stabilne identyfikatory
  numeryczne.
- **`finalized_at`** jest w formacie ISO-8601 UTC, ale część ułamkowa sekund
  jest **zmiennej długości i może być nieobecna** — to samo pole może przyjść
  jako `2026-07-06T10:15:30.482170+00:00` lub `2026-07-06T10:15:30+00:00`. Użyj
  tolerancyjnego parsera ISO-8601 i nie zakładaj precyzji mikrosekundowej.

## Weryfikacja podpisu

Każde żądanie zawiera `X-Libli-Signature: sha256=<hex>`. Aby zweryfikować:

1. Weź **surowe bajty ciała żądania** — dokładnie tak, jak zostały odebrane.
   **Nie** parsuj JSON i nie serializuj go ponownie; ponowne kodowanie (nawet
   zmiana białych znaków) zmienia bajty i podpis się nie zgodzi. Ciało na łączu
   to jednowierszowy JSON z domyślnymi odstępami (spacja po każdym `:` i `,`),
   a nie sformatowany JSON pokazany powyżej.
2. Oblicz `HMAC-SHA256` z **kluczem = Twój wspólny sekret podpisujący
   zakodowany jako bajty UTF-8** i wiadomością = tymi surowymi bajtami ciała.
3. Weź skrót szesnastkowy **małymi literami** i poprzedź go `sha256=`.
4. Porównaj z wartością nagłówka używając porównania **w stałym czasie**,
   z rozróżnianiem wielkości liter. Szesnastkowy skrót w nagłówku jest małymi
   literami — nie zamieniaj na wielkie litery ani nie normalizuj przed
   porównaniem.

Python (Flask):

```python
import hashlib
import hmac
import json

SECRET = b"your-shared-secret"  # UTF-8 bytes


def receive(request):
    raw = request.get_data()  # raw bytes — NOT request.json then re-dumped
    got = request.headers.get("X-Libli-Signature", "")
    expected = "sha256=" + hmac.new(SECRET, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(got, expected):
        return ("", 401)
    event = json.loads(raw)
    if event.get("test"):
        return ("", 200)  # verify, but never ingest a test event
    # ... upsert (see Idempotency & corrections) ...
    return ("", 200)
```

Node.js (Express):

```javascript
const crypto = require("crypto");
const SECRET = "your-shared-secret"; // utf-8

// Capture the RAW body so the signature is computed over the exact bytes:
app.use("/libli-webhook", express.raw({ type: "application/json" }));

app.post("/libli-webhook", (req, res) => {
  const raw = req.body; // Buffer of raw bytes
  const got = req.get("X-Libli-Signature") || "";
  const expected =
    "sha256=" + crypto.createHmac("sha256", SECRET).update(raw).digest("hex");
  const ok =
    got.length === expected.length &&
    crypto.timingSafeEqual(Buffer.from(got), Buffer.from(expected));
  if (!ok) return res.sendStatus(401);
  const event = JSON.parse(raw.toString("utf8"));
  if (event.test) return res.sendStatus(200); // do not ingest test events
  // ... upsert (see Idempotency & corrections) ...
  res.sendStatus(200);
});
```

PHP:

```php
<?php
$secret = 'your-shared-secret'; // utf-8
$raw = file_get_contents('php://input'); // raw bytes
$got = $_SERVER['HTTP_X_LIBLI_SIGNATURE'] ?? '';
$expected = 'sha256=' . hash_hmac('sha256', $raw, $secret);
if (!hash_equals($expected, $got)) {
    http_response_code(401);
    exit;
}
$event = json_decode($raw, true);
if (!empty($event['test'])) {
    http_response_code(200); // verify, do not ingest test events
    exit;
}
// ... upsert (see Idempotency & corrections) ...
http_response_code(200);
```

Aby sprawdzić swój weryfikator na zapisanym ciele, przelicz skrót za pomocą
`openssl` na bajtowo-dokładnym zapisanym ciele (nie pozwól, aby powłoka usunęła
końcowy znak nowej linii):

```bash
openssl dgst -sha256 -hmac "your-shared-secret" < body.json
```

## Odpowiadanie

Zwróć status HTTP **2xx**, aby potwierdzić. Każdy inny status, przekroczenie
limitu czasu lub błąd połączenia jest traktowany jako niepowodzenie i zdarzenie
jest ponawiane.

## Ponawianie i semantyka dostarczania

- Do **8 prób** na dostawę.
- Odstępy między próbami: **1, 5, 15, 60, 180, 360, 720 minut**.
- Limit czasu **10 sekund** na próbę.
- Po 8. nieudanej próbie dostawa trafia do martwej kolejki (jest porzucana).
- Przekierowania **nie** są śledzone — odpowiadaj bezpośrednio, nie używaj 3xx.

## Idempotentność i korekty

To jest kontrakt, który większość integracji rozumie źle — przeczytaj go
w całości.

- `X-Libli-Delivery` deduplikuje tylko **ponowienia pojedynczej dostawy**.
- Późniejsza **korekta wyniku to nowa dostawa** z nowym id — *nie* ponowienie.
- **Wykonaj upsert** (wstaw lub zaktualizuj) wiersz wyniku i traktuj
  **`finalized_at` jako rozstrzygające**: zignoruj przychodzące zdarzenie,
  którego `finalized_at` jest starsze niż to, co już zapisałeś.

Ustal klucz upsert na **stabilnych** polach:

- **uczeń** → `student.external_id` (jedyny identyfikator ucznia).
- **kurs** → `course.external_id`.
- **grupa** → numeryczne **`group.id`** (nie mogące być puste `external_id`;
  dwie niezmapowane grupy mają puste `external_id` i by się zderzyły).
- **jednostka** → numeryczne **`unit.id`**.

Zatem kluczem jest `(student.external_id, course.external_id, group.id,
unit.id)`, z pominięciem segmentu grupy dla zdarzenia `"group": null`.

**Reguła odbiorcy dla pustego ucznia.** Zdarzenie, którego
`student.external_id` jest puste, **nie może zostać zmapowane** do ucznia —
**odrzuć/pomiń je i zaloguj**, zamiast wykonywać upsert na pustym kluczu (co
zwinęłoby wszystkich takich uczniów w jeden wiersz). Poproś administratora
platformy Libli, aby zapewnił, że każdy synchronizowany uczeń ma `external_id`.

## Testowanie punktu końcowego

Administrator platformy Libli może kliknąć **Wyślij zdarzenie testowe** na
stronie ustawień Integracji. Wysyła to jeden podpisany przykład na Twój punkt
końcowy, abyś mógł pracować na żywej, weryfikowalnej dostawie.

Zdarzenia testowe są oznaczone na dwa sposoby — pole najwyższego poziomu
`"test": true` **oraz** `X-Libli-Delivery: test`. **Zweryfikuj podpis** (aby
potwierdzić poprawność sekretu), ale **nie przyjmuj** ich jako prawdziwych
ocen. Numeryczne identyfikatory w przykładzie poniżej (`0`) to oczywiste
wartości zastępcze, a nie prawdziwe id:

```json
{
  "test": true,
  "event": "result_finalized",
  "finalized_at": "2026-07-06T10:15:30.123456+00:00",
  "student": { "external_id": "SAMPLE-STUDENT", "email": "sample.student@example.edu", "name": "Sample Student" },
  "course":  { "external_id": "SAMPLE-COURSE", "slug": "sample-course", "title": "Sample Course" },
  "group":   { "id": 0, "external_id": "SAMPLE-GROUP", "name": "Sample Group" },
  "unit":    { "id": 0, "title": "Sample Unit" },
  "score":   { "earned": "8.00", "max": "10.00", "percent": 80.0 }
}
```

## Dla administratora platformy

Skonfiguruj punkt końcowy w **Zarządzaj → Ustawienia → Integracje**: ustaw
**Adres URL punktu końcowego** i **Sekret podpisujący**, następnie włącz
synchronizację wyników. Udostępnij ten sam sekret programiście odbiorcy, aby
mógł weryfikować podpisy. Przycisk **Wyślij zdarzenie testowe** korzysta
z **zapisanego** adresu URL i sekretu, więc zapisz ustawienia przed
testowaniem.

**Każdy uczeń, którego wyniki są synchronizowane, musi mieć `external_id`** —
jest to jedyny klucz ucznia w ładunku, a wyniki ucznia bez niego nie mogą
zostać zmapowane przez odbiorcę.
