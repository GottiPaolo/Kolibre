"""
Dove sta sul disco la cartella di un libro, e quando e' finita nel posto
sbagliato.

Una biblioteca Calibre tiene i file in `<primo autore>/<titolo> (<id>)`, col
file di ogni formato chiamato `<titolo> - <primo autore>.<est>`. Il percorso
REALE e' quello scritto in `books.path`: niente si ricava dal nome della
cartella, tutto passa da li'. Per questo un libro a cui si cambia l'autore
continua a funzionare anche se resta sotto la cartella del nome vecchio — ma
la biblioteca sul disco smette di corrispondere ai metadati, e chi la apre
con un gestore di file (o con Calibre) trova un libro sotto "Rossi Mario"
quando l'autore ormai si chiama "Mario Rossi".

La forma canonica la calcola `calibre_naming`, che e' il porting fedele
dell'algoritmo di Calibre (verificato ricalcolando i percorsi di una
biblioteca Calibre vera e confrontandoli con quelli scritti da Calibre).
Qui sopra ci sta solo la decisione: questo libro e' dove dovrebbe stare?

Una nota su cosa NON si tocca mai, che e' la parte che tiene al sicuro le
biblioteche vere:

- un libro la cui cartella non esiste sul disco (niente da spostare: e' un
  problema di file mancanti, che si segnala a parte);
- un libro la cui destinazione e' gia' occupata da qualcos'altro (non si
  sovrascrive niente, mai).
"""


from . import calibre_naming


def percorso_canonico(book_id: int, title: str, author: str) -> str:
    """Il percorso che Calibre darebbe a questo libro."""
    return calibre_naming.percorso_per_libro(book_id, title, author)


def nome_file_canonico(title: str, author: str, formati=None) -> str:
    """Il nome (senza estensione) che Calibre darebbe ai file del libro."""
    return calibre_naming.construct_file_name(
        title,
        calibre_naming.autore_di_cartella(author),
        calibre_naming.lunghezza_estensione(formati),
    )


def _normalizza(percorso: str) -> str:
    return (percorso or "").replace("\\", "/").strip("/")


def percorso_corretto(percorso_attuale: str, autore: str, book_id: int = 0, titolo: str = "") -> str:
    """
    Il percorso che questo libro dovrebbe avere, o stringa vuota se sta gia'
    dove deve stare.

    Prima questa funzione cambiava solo la cartella d'autore e confrontava in
    modo tollerante (accenti e maiuscole ignorati, nome completo o primo
    autore indifferenti). Andava bene finche' Kolibre aveva una convenzione
    PROPRIA e l'unica cosa da correggere erano i rinomini: essere tolleranti
    evitava di spostare mezza biblioteca solo perche' Calibre scrive
    "Emile Zola" dove noi scrivevamo "Émile Zola".

    Ora che Kolibre nomina esattamente come Calibre, quella tolleranza
    lavorerebbe contro: "Émile Zola" e "Mario Rossi & Anna Bianchi" sono
    proprio le cartelle che vanno ricondotte alla forma di Calibre. Il
    confronto e' quindi con la forma canonica, e basta.
    """
    if not percorso_attuale or not book_id:
        return ""
    atteso = percorso_canonico(book_id, titolo, autore)
    if _normalizza(atteso) == _normalizza(percorso_attuale):
        return ""
    return atteso


def motivo(percorso_attuale: str, autore: str, titolo: str) -> str:
    """
    Perche' questo libro risulta fuori posto — in una riga, per la pagina di
    manutenzione: chi sta per spostare mille cartelle ha diritto di sapere
    per quale ragione, non solo quante.
    """
    pezzi = _normalizza(percorso_attuale).split("/")
    cartella = pezzi[0] if pezzi else ""
    nomi = calibre_naming.string_to_authors(autore or "")
    if not cartella.isascii():
        return "accenti nel nome della cartella"
    if len(nomi) > 1 and cartella == calibre_naming.ascii_filename(autore):
        return "cartella intestata a tutti gli autori invece che al primo"
    if len(pezzi) > 1 and len(max(pezzi, key=len)) > calibre_naming.PATH_LIMIT:
        return "nome troppo lungo"
    return "autore o titolo cambiati dopo la creazione"
