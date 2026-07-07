# Integracje (synchronizacja ocen)

libli może przesyłać zatwierdzone wyniki quizów do systemu informacji o
szkole (SIS) lub e-dziennika za pomocą podpisanego webhooka. Skonfiguruj
punkt odbioru w **Administracja → Ustawienia instytucji → Integracje**.

## Konfiguracja

Podaj **adres URL punktu odbioru** oraz **sekret podpisujący**, współdzielony
z integracją po stronie Twojego SIS. Gdy oba pola są ustawione, użyj
przycisku **Wyślij zdarzenie testowe**, aby wysłać przykładową dostawę do
Twojego odbiornika i upewnić się, że przyjmuje żądanie i poprawnie
weryfikuje podpis, zanim zaczniesz polegać na rzeczywistej dostawie ocen.
Lista ostatnich dostaw na tej samej zakładce pokazuje wynik dostaw
testowych i rzeczywistych, wraz z ponowieniami.

## Co jest wysyłane

W synchronizacji ocen biorą udział wyłącznie kursy z ustawionym **Kodem
przedmiotu w rejestrze zewnętrznym** (zobacz [Zakładanie
kursu](create-a-course)); wyniki kursu bez tego kodu nigdy nie opuszczają
platformy. Dostawa jest kolejkowana za każdym razem, gdy w zsynchronizowanym
kursie zostaje zatwierdzone rozwiązanie quizu.

## Kontrakt odbiornika

Pełny kształt danych, nagłówki, weryfikację podpisu HMAC oraz semantykę
ponowień i idempotencji, jaką musi zaimplementować Twój odbiornik, opisuje
dedykowany **[przewodnik po webhooku SIS](/integrations/webhook/)** — ten
sam przewodnik można wskazać bezpośrednio programiście integrującemu
system, w dowolnym z dwóch języków.
