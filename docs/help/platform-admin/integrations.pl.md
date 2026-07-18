# Integracje (synchronizacja ocen)

libli może przesyłać zatwierdzone wyniki quizów do systemu informacji o
szkole (SIS) lub e-dziennika za pomocą podpisanego webhooka. Skonfiguruj
punkt odbioru w **Administracja → Ustawienia instytucji → Integracje**.

![Zakładka ustawień integracji](static:core/img/help/integrations.pl.png)

## Konfiguracja

Rzeczywista synchronizacja ocen wymaga **czterech elementów**: **Adresu URL
punktu końcowego**, **Klucza podpisującego** współdzielonego z integracją
po stronie Twojego SIS, zaznaczonej i zapisanej opcji **Włącz
synchronizację wyników** oraz kursu z ustawionym **Kodem przedmiotu w
rejestrze zewnętrznym** (zobacz [Zakładanie kursu](create-a-course)).

Gdy adres URL i klucz podpisujący są zapisane, przycisk **Wyślij zdarzenie
testowe** wysyła przykładową dostawę do Twojego odbiornika, dzięki czemu
możesz upewnić się, że przyjmuje żądanie i poprawnie weryfikuje podpis. Ten
test sprawdza jedynie, czy adres URL i klucz są zapisane — **nie**
sprawdza, czy opcja **Włącz synchronizację wyników** jest zaznaczona, więc
pozytywny wynik testu potwierdza tylko, że Twój odbiornik działa, a nie że
rzeczywista synchronizacja ocen jest włączona. Zaznacz **Włącz
synchronizację wyników** osobno, zanim zaczniesz polegać na rzeczywistej
dostawie ocen. Lista ostatnich dostaw na tej samej zakładce pokazuje wynik
dostaw testowych i rzeczywistych, wraz z ponowieniami.

## Co jest wysyłane

W synchronizacji ocen biorą udział wyłącznie kursy z ustawionym **Kodem
przedmiotu w rejestrze zewnętrznym**; wyniki kursu bez tego kodu nigdy nie
opuszczają platformy. Gdy w zsynchronizowanym kursie zostaje zatwierdzone
rozwiązanie quizu, kolejkowana jest jedna dostawa dla każdej grupy, do
której należy uczeń — a jeśli uczeń nie należy do żadnej grupy, kolejkowana
jest dokładnie jedna dostawa, nigdy zero. Jeśli rozwiązanie zawiera pytania
oczekujące na ręczną weryfikację, żadna dostawa nie jest kolejkowana w
momencie oddania; jedna zostaje kolejkowana dopiero po zakończeniu
weryfikacji i ostatecznym ustaleniu wyniku.

## Kontrakt odbiornika

Pełny kształt danych, nagłówki, weryfikację podpisu HMAC oraz semantykę
ponowień i idempotencji, jaką musi zaimplementować Twój odbiornik, opisuje
dedykowany **[przewodnik po webhooku SIS](/integrations/webhook/)** — ten
sam przewodnik można wskazać bezpośrednio programiście integrującemu
system, w dowolnym z dwóch języków.
