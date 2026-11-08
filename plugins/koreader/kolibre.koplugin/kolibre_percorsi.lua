--[[--
Dove stanno le cose, quando KOReader non lo dice allo stesso modo in tutte
le sue versioni.

**Perche' questo modulo esiste.** Il 03/11/2026 aprire il menu' delle patch
faceva crollare il plugin:

    main.lua:3588: attempt to call method 'getPatchesDir' (a nil value)

`DataStorage:getPatchesDir()` esiste **solo su master** di KOReader: in
tutte le versioni pubblicate — verificato su v2023.04, v2024.01, v2024.07 e
v2025.04 — quel metodo non c'e', e la cartella delle patch e' composta a
mano dal suo stesso `userpatch.lua` come `getDataDir() .. "/patches"`.
L'errore e' stato leggere la documentazione su `master` invece che su una
release.

Sta in un modulo suo, e non dentro `main.lua`, per un motivo preciso: cosi'
si puo' PROVARE senza KOReader, passandogli finti `DataStorage` fatti come
quelli delle versioni vecchie e nuove (vedi
la prova «percorso_delle_patch»). Un difetto che si vede
solo aprendo un menu' su un dispositivo vero e' un difetto che si scopre
tardi.
--]]--

local KolibrePercorsi = {}

-- La cartella dei DATI di KOReader, risolta in un percorso assoluto.
--
-- **Perche' non basta `getDataDir()`.** Su un Kindle quel metodo risponde
-- `"."` — e' l'ultimo ramo di `datastorage.lua` di KOReader, quello che vale
-- quando non c'e' `KO_HOME`, non e' Android e non ci sono KO_MULTIUSER,
-- AppImage o Flatpak. Per KOReader va bene, perche' la sua cartella di
-- lavoro **e'** quella d'installazione; per chi deve **creare** una
-- sottocartella no: un percorso relativo passato a una funzione che lo
-- ricompone segmento per segmento diventa un percorso alla radice del
-- filesystem, e la cartella nasce nel posto sbagliato (o non nasce, perche'
-- la radice e' in sola lettura). E' il difetto dei dizionari dell'08/11/2026,
-- riprodotto sul KOReader vero.
--
-- `DataStorage` e' il modulo di KOReader (si passa come argomento, non si
-- richiede qui dentro, perche' e' quello che rende provabile la funzione).
-- `cartella_corrente` e' facoltativa: una funzione che torna la cartella di
-- lavoro, usata solo quando nemmeno KOReader sa risolvere il suo `"."`.
--
-- Torna `nil` se da `DataStorage` non si ricava niente: meglio dirlo che
-- scrivere a caso. L'ultima spiaggia e' il percorso relativo, e chi lo usa
-- deve saperlo.
function KolibrePercorsi.cartellaDeiDati(DataStorage, cartella_corrente)
    if type(DataStorage) ~= "table" or type(DataStorage.getDataDir) ~= "function" then
        return nil
    end
    local dati = DataStorage:getDataDir()
    if type(dati) ~= "string" or dati == "" then return nil end
    dati = (dati:gsub("/+$", ""))
    if dati == "" then return "/" end
    if dati:sub(1, 1) == "/" then return dati end

    -- Percorso relativo. `getFullDataDir()` e' la forma risolta dello stesso
    -- percorso, e c'e' in tutte le versioni guardate.
    if type(DataStorage.getFullDataDir) == "function" then
        local piena = DataStorage:getFullDataDir()
        if type(piena) == "string" and piena:sub(1, 1) == "/" then
            return (piena:gsub("/+$", ""))
        end
    end
    if type(cartella_corrente) == "function" then
        local cwd = cartella_corrente()
        if type(cwd) == "string" and cwd ~= "" then
            cwd = (cwd:gsub("/+$", ""))
            local resto = (dati:gsub("^%.$", ""):gsub("^%./", ""))
            return resto == "" and cwd or (cwd .. "/" .. resto)
        end
    end
    return dati
end

-- La cartella delle patch di KOReader, risolta.
--
-- Su master KOReader la sa dire da se'; in tutte le versioni pubblicate si
-- compone come fa il suo stesso `userpatch.lua`, cioe' dalla cartella dei
-- dati — che e' il motivo per cui questa funzione ora passa da
-- `cartellaDeiDati` invece di rifarne il lavoro.
--
-- Torna sempre un percorso ASSOLUTO quando e' possibile ricavarlo, perche'
-- chi lo usa deve poter creare la cartella se non c'e'. Torna nil se da
-- `DataStorage` non si ricava niente.
function KolibrePercorsi.cartellaDellePatch(DataStorage, cartella_corrente)
    if type(DataStorage) ~= "table" then return nil end

    if type(DataStorage.getPatchesDir) == "function" then
        -- KOReader recenti (per ora solo master): lo chiede a lui.
        local sua = DataStorage:getPatchesDir()
        if type(sua) == "string" and sua ~= "" and sua:sub(1, 1) == "/" then
            return sua
        end
    end
    local dati = KolibrePercorsi.cartellaDeiDati(DataStorage, cartella_corrente)
    if dati == nil then return nil end
    return dati .. "/patches"
end

--- La cartella in cui va installato un dizionario mandato dal portale.
--
-- **Due cose che il plugin sbagliava, entrambe trovate l'08/11/2026.**
--
-- 1. componeva il percorso da `getDataDir()` grezzo — vedi
--    `cartellaDeiDati` qui sopra per cosa succede su un Kindle;
-- 2. scriveva in `<dati>/dict`, mentre KOReader cerca i dizionari StarDict
--    in **`<dati>/data/dict`** (verificato nel codice che gira,
--    `readerdictionary.lua:118`, v2026.03). Un livello piu' in alto: il
--    download riusciva e il dizionario non si usava. Il commento sopra la
--    funzione che scaricava diceva `data/dict/`; il codice aveva perso il
--    `data/`.
--
-- **Perche' la lingua si controlla.** Quel codice arriva dalla risposta del
-- server e finisce in un percorso del filesystem. Un valore con `/` o `..`
-- dentro scriverebbe fuori dalla cartella dei dizionari. Si accettano solo
-- lettere, cifre, `-` e `_`: i codici di lingua sono quelli.
function KolibrePercorsi.cartellaDeiDizionari(DataStorage, lingua, cartella_corrente)
    if type(lingua) ~= "string" or lingua == "" then return nil end
    if lingua:match("^[A-Za-z0-9_%-]+$") == nil then return nil end
    local dati = KolibrePercorsi.cartellaDeiDati(DataStorage, cartella_corrente)
    if dati == nil then return nil end
    return dati .. "/data/dict/kolibre-" .. lingua
end

-- Dove va scritto un libro che sta arrivando sul dispositivo.
--
-- `voce` e' la voce del manifesto per (biblioteca, libro, formato), oppure
-- `nil`. `calcolato` e' il percorso che si ricava dai metadati di adesso.
-- `esiste` e' una funzione che dice se un percorso e' un file: si passa
-- come argomento, e non si chiama `lfs` qui dentro, perche' e' quello che
-- rende provabile questa decisione senza KOReader.
--
-- Torna due valori: il percorso, e il **motivo** della scelta. Il motivo non
-- e' decorativo — chi chiama lo scrive nel log, ed e' l'unico modo di
-- accorgersi dal registro di un dispositivo che un libro e' stato riscritto
-- al posto di essere raddoppiato.
--
--   `nuovo`            il dispositivo non ha quel libro: si usa il calcolato.
--   `gia_presente`     c'e', e il file e' la': si scrive **sopra quello**.
--   `sparito`          il manifesto lo diceva, ma il file non c'e' piu'.
--   `non_verificabile` non si e' potuto guardare il disco.
--
-- **Perche' esiste.** Fino al 05/11/2026 il percorso era sempre e solo il
-- calcolato, e il manifesto non veniva guardato. Bastava quindi che i
-- metadati fossero cambiati — o che fosse cambiata la convenzione del nome,
-- come e' successo due volte — perche' il file nuovo nascesse ACCANTO al
-- vecchio invece che al suo posto. Misurato sul Kindle di Paolo: 88 libri su
-- 211 avevano un percorso che non si ricalcolava piu' uguale, e 21 erano
-- gia' in doppia copia. Vedi la prova «una_sola_copia_del_libro».
--
-- **Perche' si riscrive sopra e non si rinomina.** KOReader tiene la lettura
-- — posizione, evidenziazioni, note — in una cartella `.sdr` accanto al file
-- e col suo nome: spostare il libro senza spostare quella perde tutto cio'
-- che ci sta dentro. Allineare i nomi dei file ai metadati e' un lavoro suo,
-- e va fatto spostando entrambe le cose.
function KolibrePercorsi.doveMettere(voce, calcolato, esiste)
    local registrato = type(voce) == "table" and voce.path or nil
    if type(registrato) ~= "string" or registrato == "" then
        return calcolato, "nuovo"
    end
    if type(esiste) ~= "function" then
        -- Senza un modo di guardare il disco non si indovina: meglio un file
        -- in piu' che scrivere sopra qualcosa che non si e' guardato.
        return calcolato, "non_verificabile"
    end
    if esiste(registrato) then
        return registrato, "gia_presente"
    end
    return calcolato, "sparito"
end

-- La cartella che contiene un percorso, senza la barra finale.
--
-- Serve perche' la cartella da creare e' quella del percorso **scelto**, non
-- quella calcolata dai metadati: crearle entrambe lascerebbe sul dispositivo
-- una cartella d'autore vuota per ogni libro riscritto al suo vecchio posto.
function KolibrePercorsi.cartellaDi(percorso)
    if type(percorso) ~= "string" then return nil end
    return percorso:match("^(.*)/[^/]+$")
end

return KolibrePercorsi
