// @ts-check
/* Kalmido web client: the line of the day, a Dada quote (2.955.0, #5239), loaded on demand (lazyload.js LD_MODS quotes).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   Shown alone above the sign-in form (account.js authScreen) and below the greeting on Today (dashboard.js viewHome); the
   callers ask qd_slot() (account.js), which loads this file on first use. Only real quotes of authors who died before 1956
   (public domain), wording as in the original (spelling included); the translations are our own. The texts are data, no
   i18n keys; the original's wording stays as it is. 2.1017.0 (#5784, replaces the original + translation of #5239): the quote
   shows ONCE, in the interface language (qd_text): the original when it is in that language, else the German text for a
   German interface and the English one for every other (French reads the French original or the English translation);
   below it only the author. 2.1030.0 (#5785): Spanish, Italian, Dutch and French have their own texts, each in a file of its
   own loaded on demand (quotes_dada_<code>.js, lazyload.js LD_MODS quotes_<code>, account.js qd_slot), which fills QD_TR;
   English stays the fallback while that file is missing. Sound poems are never translated. No text ends on a comma, semicolon or colon. Work / year only as the tooltip of the author's name (none for Vaché and Pansaers).
   The line changes once a day (the local date), the same on the sign-in page and on Today; redrawing keeps it. */
'use strict';

// [no. of the research list, language of the original, original, German, English, author, work + year for the tooltip, sound poem]
/** @type {Array<[number, string, string, string, string, string, string, number]>} */
const QD_LIST = [
  [1, "de", "Was wir Dada nennen, ist ein Narrenspiel aus dem Nichts", "", "What we call Dada is a fool's game out of nothingness", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [2, "de", "Der Dadaist liebt das Außergewöhnliche, ja das Absurde.", "", "The Dadaist loves the extraordinary, indeed the absurd.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [3, "de", "Seien wir neu und erfinderisch von Grund aus. Dichten wir das Leben täglich um.", "", "Let us be new and inventive from the ground up. Let us rewrite life every day.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [4, "de", "Dada heißt im Rumänischen Ja, Ja, im Französischen Hotto- und Steckenpferd.", "", "In Romanian, Dada means yes, yes; in French, a rocking horse and a hobbyhorse.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [5, "de", "Wir begrüßten das Kind, in der Kunst und im Leben.", "", "We welcomed the child, in art and in life.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [6, "de", "Alles Bosseln und Spielen schafft Grazie", "", "All tinkering and playing creates grace", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [7, "de", "Vielleicht ist Produktivität selbst nur eine Grazie.", "", "Perhaps productivity itself is only a grace.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [8, "de", "Man darf sich nicht selber als Polizist behandeln.", "", "One must not treat oneself as a policeman.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [9, "de", "Lebendigkeit und Grazie sind fast identisch.", "", "Liveliness and grace are almost identical.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [10, "de", "Rumpeln die Dinge dann, mögen sie rumpeln.", "", "If things rumble then, let them rumble.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [11, "de", "So in der Nacht und bei Mondschein verstehen wir uns ganz gut.", "", "At night like this, by moonlight, we understand each other quite well.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [12, "de", "Dadaist: kindlicher, donquichottischer Mensch, der in Wortspiele und grammatikalische Figuren verstrickt ist.", "", "Dadaist: a childlike, quixotic person entangled in wordplay and grammatical figures.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [13, "de", "Aber es gibt Worte, die zugleich Bilder sind.", "", "But there are words that are pictures at the same time.", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [14, "de", "Der Dadaismus — ein Maskenspiel, ein Gelächter?", "", "Dadaism — a masquerade, a burst of laughter?", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 0],
  [15, "de", "gadji beri bimba / glandridi lauli lonni cadori", "", "", "Hugo Ball", "Die Flucht aus der Zeit, 1927", 1],
  [16, "de", "jolifanto bambla ô falli bambla", "", "", "Hugo Ball", "Karawane, 1920", 1],
  [18, "de", "Blau ist die Farbe deines gelben Haares. / Rot ist das Girren deines grünen Vogels.", "", "Blue is the colour of your yellow hair. / Red is the cooing of your green bird.", "Kurt Schwitters", "An Anna Blume, 1919", 0],
  [19, "de", "Anna Blume! Anna, a-n-n-a, ich träufle deinen Namen.", "", "Anna Blume! Anna, a-n-n-a, I trickle your name.", "Kurt Schwitters", "An Anna Blume, 1919", 0],
  [20, "de", "Du trägst den Hut auf deinen Füßen und wanderst auf die Hände, auf den Händen wanderst du.", "", "You wear your hat on your feet and walk on your hands, on your hands you walk.", "Kurt Schwitters", "An Anna Blume, 1919", 0],
  [21, "de", "Fümms bö wö tää zää Uu, / pögiff, / kwii Ee.", "", "", "Kurt Schwitters", "Ursonate, 1932", 1],
  [22, "de", "Lanke trr gll (munter) / pe pe pe pe pe / Ooka ooka ooka ooka", "", "", "Kurt Schwitters", "Ursonate, 1932", 1],
  [23, "de", "Rrummpff tillff toooo?", "", "", "Kurt Schwitters", "Ursonate, 1932", 1],
  [24, "de", "Silberne Fische schwimmen in der Luft. / Sie verbrennen sich nicht.", "", "Silver fish swim in the air. / They do not burn themselves.", "Kurt Schwitters", "Die Welt, 1919", 0],
  [25, "de", "Und Glimmergluten sanftet Welt.", "", "And glimmer-glow softens the world.", "Kurt Schwitters", "Abend, 1919", 0],
  [26, "de", "Das ergibt keinen Sinn, aber es erzeugt Weltgefühl, und darauf kommt es an.", "", "That makes no sense, but it produces a feeling for the world, and that is what matters.", "Kurt Schwitters", "Anna Blume. Dichtungen, 1919", 0],
  [27, "de", "Zwölf Uhr uhren alle Uhren.", "", "Twelve o'clock, all the clocks are clocking.", "Kurt Schwitters", "Die rote Marie, 1919", 0],
  [29, "de", "Ich fliege in dem großen Raum. / Ich mische mich in jeden Traum", "", "I fly through the great space. / I mingle with every dream", "Emmy Hennings", "Die letzte Freude, 1913", 0],
  [30, "de", "Eine Uhr schlägt langsam vier. / Und ich weiß von keiner Zeit", "", "A clock slowly strikes four. / And I know of no time", "Emmy Hennings", "Die letzte Freude, 1913", 0],
  [31, "de", "Ich wehe durch weiße Wolken in offene Arme.", "", "I drift through white clouds into open arms.", "Emmy Hennings", "Die letzte Freude, 1913", 0],
  [32, "de", "Irgendwo in der Ferne vergeht die Zeit", "", "Somewhere in the distance, time passes", "Emmy Hennings", "Die letzte Freude, 1913", 0],
  [33, "de", "Ein Hund ist eine Hängematte.", "", "A dog is a hammock.", "Walter Serner", "Letzte Lockerung. manifest dada, 1920", 0],
  [34, "de", "Ach die lieben weißen Porzellanteller!", "", "Oh, the dear white porcelain plates!", "Walter Serner", "Letzte Lockerung. manifest dada, 1920", 0],
  [35, "de", "Gegenwärtig schätze ich sehr die Vokabel ‚Rosinen‘.", "", "At present I greatly esteem the word 'raisins'.", "Walter Serner", "Letzte Lockerung. manifest dada, 1920", 0],
  [36, "de", "Jede Regel hat ihre Ausnahme, zweifellos. Also regelmäßig.", "", "Every rule has its exception, no doubt. So, regularly.", "Walter Serner", "Letzte Lockerung. manifest dada, 1920", 0],
  [37, "de", "Fummelmond und ferngefimmel", "", "Fumble-moon and far-off flicker", "Johannes Theodor Baargeld", "Bimmelresonnanz II, 1920", 0],
  [38, "de", "Lämmergeiger zieht die Wäscheleine", "", "The lamb-fiddler pulls the washing line", "Johannes Theodor Baargeld", "Bimmelresonnanz II, 1920", 0],
  [39, "fr", "Les jours de pluie ressemblent aux vacances.", "Regentage sehen aus wie Ferien.", "Rainy days look like holidays.", "Francis Picabia", "Jésus-Christ Rastaquouère, 1920", 0],
  [40, "fr", "Il y a les lacs et les iles, ce qui est exactement la même chose.", "Es gibt die Seen und die Inseln, und das ist genau dasselbe.", "There are the lakes and the islands, which is exactly the same thing.", "Francis Picabia", "Jésus-Christ Rastaquouère, 1920", 0],
  [41, "fr", "Il y a des hommes qui ont la tête en bas, comme les plantes, et qui regardent avec leurs pieds !", "Manche Menschen haben den Kopf unten, wie die Pflanzen, und schauen mit den Füßen!", "There are people who have their heads at the bottom, like plants, and who look with their feet!", "Francis Picabia", "Jésus-Christ Rastaquouère, 1920", 0],
  [42, "fr", "Il y a mille choses pour passer le temps, et il n'y a rien pour passer le temps.", "Es gibt tausend Dinge, um die Zeit zu vertreiben, und nichts, um die Zeit zu vertreiben.", "There are a thousand things to pass the time, and there is nothing to pass the time.", "Francis Picabia", "Jésus-Christ Rastaquouère, 1920", 0],
  [43, "fr", "Mais il est 11 h. 1/2, il faut que j'aille prendre mon bain.", "Aber es ist halb zwölf, ich muss jetzt baden gehen.", "But it is half past eleven, I must go and take my bath.", "Francis Picabia", "Le Pilhaou-Thibaou, 1921", 0],
  [44, "fr", "Les crocodiles sont mes amis", "Die Krokodile sind meine Freunde", "The crocodiles are my friends", "Francis Picabia", "Le Pilhaou-Thibaou, 1921", 0],
  [45, "fr", "le cœur représente le début des promenades", "Das Herz ist der Anfang der Spaziergänge", "the heart stands for the start of the walks", "Francis Picabia", "Le Pilhaou-Thibaou, 1921", 0],
  [46, "fr", "Plus on plaît plus on déplaît", "Je mehr man gefällt, desto mehr missfällt man", "The more one pleases, the more one displeases", "Francis Picabia", "Le Pilhaou-Thibaou, 1921", 0],
  [47, "fr", "Ce que j'aime le moins chez les autres, c'est moi.", "Was ich an den anderen am wenigsten mag, bin ich.", "What I like least in others is me.", "Francis Picabia", "391, 1924", 0],
  [48, "fr", "Amis joyeux ôtent la housse du canapé / Pour assister par la fenêtre au concert des abeilles.", "Fröhliche Freunde nehmen den Bezug vom Sofa, um durchs Fenster dem Konzert der Bienen zu lauschen.", "Cheerful friends take the cover off the sofa / To listen through the window to the bees’ concert.", "Francis Picabia", "Ceinture de soie, 1918", 0],
  [49, "fr", "il fait Toujours un Temps admirable aux bains de vapeur", "Im Dampfbad ist Immer Herrliches Wetter", "the weather is Always admirable in the steam baths", "Francis Picabia", "Pensées sans langage, 1919", 0],
  [50, "fr", "Bonjour au tailleur de pierre mon voisin", "Grüß mir den Steinmetz, meinen Nachbarn", "Greetings to the stonemason, my neighbour", "Jacques Vaché", "", 0],
  [51, "fr", "Je comprends mal le Temps, tout compte fait", "Alles in allem verstehe ich die Zeit schlecht", "All things considered, I understand Time poorly", "Jacques Vaché", "", 0],
  [52, "fr", "J'œuvre des dessins drôles, à l'aide de crayons de couleur sur du papier gros grain", "Ich werkle an drolligen Zeichnungen, mit Buntstiften auf grobkörnigem Papier", "I craft funny drawings, with coloured pencils on coarse-grained paper", "Jacques Vaché", "", 0],
  [54, "fr", "Dans le vert fou de l'herbe, je roulais comme un œuf.", "Im irren Grün des Grases rollte ich wie ein Ei.", "In the wild green of the grass, I rolled like an egg.", "Arthur Cravan", "Maintenant, 1912", 0],
  [55, "fr", "chaque fleur me transforme en papillon", "Jede Blume verwandelt mich in einen Schmetterling", "every flower turns me into a butterfly", "Arthur Cravan", "Maintenant, 1913", 0],
  [56, "fr", "souvent, j'adore un caillou", "Oft bete ich einen Kieselstein an", "often, I adore a pebble", "Arthur Cravan", "Maintenant, 1913", 0],
  [57, "fr", "Que faut-il pour être heureux? Un peu d'encre!", "Was braucht man zum Glücklichsein? Ein bisschen Tinte!", "What does it take to be happy? A little ink!", "Jacques Rigaut", "Lignes, 1922", 0],
  [58, "fr", "Il n'y a pas de fumée sans fil.", "Kein Rauch ohne Faden.", "There is no smoke without thread.", "Jacques Rigaut", "Lignes, 1922", 0],
  [59, "fr", "Prends la vie comme le vent, / Avec ton nez. / Reste tranquille.", "Nimm das Leben wie den Wind, / mit der Nase. / Bleib ganz ruhig.", "Take life like the wind, / With your nose. / Stay calm.", "Paul Éluard", "Les animaux et leurs hommes, les hommes et leurs animaux, 1920", 0],
  [60, "fr", "Le poisson avance / Comme un doigt dans un gant", "Der Fisch kommt voran / wie ein Finger im Handschuh", "The fish moves on / Like a finger in a glove", "Paul Éluard", "Les animaux et leurs hommes, les hommes et leurs animaux, 1920", 0],
  [61, "fr", "Le monde rit, / Le monde est heureux, content et joyeux.", "Die Welt lacht, / die Welt ist glücklich, zufrieden und froh.", "The world laughs, / The world is happy, content and joyful.", "Paul Éluard", "Les animaux et leurs hommes, les hommes et leurs animaux, 1920", 0],
  [62, "fr", "Amour des fantaisies permises, / Du soleil, / Des citrons, / Du mimosa léger.", "Liebe zu erlaubten Launen, / zur Sonne, / zu Zitronen, / zur leichten Mimose.", "Love of permitted fancies, / Of the sun, / Of lemons, / Of light mimosa.", "Paul Éluard", "Les animaux et leurs hommes, les hommes et leurs animaux, 1920", 0],
  [63, "fr", "Il siffle comme tous les trains.", "Er pfeift wie alle Züge.", "He whistles like all trains.", "Paul Éluard", "Julot, 1920", 0],
  [64, "fr", "J'ai jeté ma lampe dans le jardin pour qu'il voie clair et je me suis couché.", "Ich habe meine Lampe in den Garten geworfen, damit er klar sieht, und bin schlafen gegangen.", "I threw my lamp into the garden so that it could see clearly, and went to bed.", "Paul Éluard", "Les nécessités de la vie et les conséquences des rêves, 1921", 0],
  [65, "fr", "La table à voir, la chaise pour s'asseoir / Et l'air à respirer.", "Der Tisch zum Ansehen, der Stuhl zum Sitzen / und die Luft zum Atmen.", "The table to look at, the chair to sit on / And the air to breathe.", "Paul Éluard", "Les nécessités de la vie et les conséquences des rêves, 1921", 0],
  [66, "fr", "Dans leur fort les escargots / tournent la roue de l'Univers", "In ihrer Burg drehen die Schnecken / das Rad des Universums", "In their fortress the snails / turn the wheel of the Universe", "Céline Arnauld", "Luna Park, 1920", 0],
  [67, "fr", "Au Luna Park on jongle / avec les cœurs en cristal", "Im Luna Park jongliert man / mit Herzen aus Kristall", "At Luna Park they juggle / with hearts of crystal", "Céline Arnauld", "Luna Park, 1920", 0],
  [68, "fr", "il inonde de soleil ceux qui vivent dans le froid, dans l'obscurité et dans l'ennui.", "Er überflutet mit Sonne alle, die in Kälte, Dunkelheit und Langeweile leben.", "it floods with sun those who live in cold, darkness and boredom.", "Céline Arnauld", "Projecteur, 1920", 0],
  [69, "fr", "Tout est dada. / Chacun a ses dadas.", "Alles ist Dada. / Jeder hat seine Steckenpferde.", "Everything is dada. / Everyone has their hobbyhorses.", "Paul Dermée", "Qu'est-ce que Dada !, 1920", 0],
  [70, "fr", "Mon perroquet reverdit à chaque printemps, mais son jargon hélas ne change pas.", "Mein Papagei wird jeden Frühling wieder grün, doch sein Kauderwelsch ändert sich leider nicht.", "My parrot turns green again every spring, but alas, his jargon does not change.", "Paul Dermée", "Projecteur, 1920", 0],
  [71, "fr", "n'avais-je pas pour 300 francs belges de bonheur à la hausse dans la poche de mon gilet", "Hatte ich nicht für 300 belgische Francs steigendes Glück in der Westentasche", "had I not 300 Belgian francs’ worth of rising happiness in my waistcoat pocket", "Clément Pansaers", "", 0],
  [72, "fr", "carrousel sur un cochon galopant à 75 à l'heure placidement faire le tour du monde", "Karussell: auf einem galoppierenden Schwein mit 75 Sachen gemächlich um die Welt", "carousel: on a pig galloping at 75 an hour, placidly going round the world", "Clément Pansaers", "", 0],
  [73, "en", "Wheels are growing on rose-bushes / gray and affectionate", "Räder wachsen an Rosenbüschen / grau und zärtlich", "", "Elsa von Freytag-Loringhoven", "Affectionate, 1922", 0],
  [74, "en", "Ah—the sun—a scarlet balloon", "Ach — die Sonne — ein scharlachroter Ballon", "", "Elsa von Freytag-Loringhoven", "Buddha, 1920", 0],
  [75, "en", "Circle! / Sufficient! / Most importantly round!", "Kreis! / Genügt! / Vor allem: rund!", "", "Elsa von Freytag-Loringhoven", "Buddha, 1920", 0],
  [76, "en", "tripping—swishing—frolicking— / courtesing—careening—brushing—", "trippelnd — raschelnd — tollend — / knicksend — schlingernd — streifend —", "", "Elsa von Freytag-Loringhoven", "Appalling Heart, 1920", 0],
  [77, "fr", "Mon coucher à lieu régulièrement à 22 h. 37.", "Mein Zubettgehen erfolgt regelmäßig um 22.37 Uhr.", "I go to bed regularly at 10.37 p.m.", "Erik Satie", "Mémoires d'un amnésique, 1913", 0],
  [78, "fr", "Je respire avec soin (peu à la fois). Je danse très rarement.", "Ich atme mit Sorgfalt (wenig auf einmal). Ich tanze sehr selten.", "I breathe with care (a little at a time). I dance very rarely.", "Erik Satie", "Mémoires d'un amnésique, 1913", 0],
  [79, "fr", "D'aspect très sérieux, si je ris, c'est sans le faire exprès. Je m'en excuse toujours et avec affabilité.", "Ich sehe sehr ernst aus; lache ich, dann ohne Absicht. Ich entschuldige mich stets dafür, und zwar liebenswürdig.", "Very serious in appearance, if I laugh, it is without meaning to. I always apologise for it, and affably.", "Erik Satie", "Mémoires d'un amnésique, 1913", 0],
  [80, "fr", "Le phonomètre à la main, je travaille joyeusement et sûrement.", "Den Phonometer in der Hand, arbeite ich fröhlich und zuverlässig.", "Phonometer in hand, I work joyfully and surely.", "Erik Satie", "Mémoires d'un amnésique, 1912", 0],
  [81, "fr", "Pour écrire mes “ Pièces Froides ”, je me suis servi d'un caléidophone-enregistreur. Cela prit sept minutes.", "Für meine „Kalten Stücke“ benutzte ich einen Kaleidophon-Aufzeichner. Es dauerte sieben Minuten.", "To write my “Cold Pieces”, I used a recording kaleidophone. It took seven minutes.", "Erik Satie", "Mémoires d'un amnésique, 1912", 0]
];
// 2.1030.0 (#5785): interface language -> {no. of the quote: its text}; filled by quotes_dada_es/fr/it/nl.js (no entry for a
// sound poem, nor for an original in that language)
/** @type {Record<string, Record<number, string>>} */
const QD_TR = {};
// the day number of a local date (the same day everywhere on this device, no time zone jump at midnight UTC)
const qd_day = (d = new Date()) => Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 864e5);
// the quote of a day: a fixed step through the list (coprime to its length, so every quote comes once before one repeats,
// and two neighbouring days rarely show the same author)
function qd_pick(d = new Date()) {
  const n = QD_LIST.length, gcd = (/** @type {number} */ a, /** @type {number} */ b) => b ? gcd(b, a % b) : a;
  let step = 31;
  while (gcd(step, n) !== 1) step++;
  return QD_LIST[((qd_day(d) * step) % n + n) % n];
}
// 2.1017.0 (#5784): the one text for the interface language -> [text, its language]: the original in its own language and for
// a sound poem; German for a German interface; 2.1030.0 (#5785): the own text of es / fr / it / nl (QD_TR, once its file is
// in); English for every other one (and while that file is missing)
function qd_text(/** @type {[number, string, string, string, string, string, string, number]} */ q, /** @type {string} */ ui) {
  const [n, lang, orig, de, en, , , sound] = q;
  if (sound || lang === ui) return [orig, lang];
  if (ui === 'de') return de ? [de, 'de'] : [orig, lang];
  const t = QD_TR[ui]?.[n];
  if (t) return [t, ui];
  return lang !== 'en' && en ? [en, 'en'] : [orig, lang];
}
// the line as a node: <figure class="qd cls"><blockquote lang>text</blockquote><figcaption>— author</figcaption></figure>
function qd_node(/** @type {string} */ cls, d = new Date()) {
  const q = qd_pick(d), ui = typeof I18N !== 'undefined' ? I18N.code : 'en', [tx, tl] = qd_text(q, ui);
  const fig = document.createElement('figure'), bq = document.createElement('blockquote'), cap = document.createElement('figcaption'), au = document.createElement('span');
  fig.className = 'qd' + (cls ? ' ' + cls : ''); fig.dataset.qdn = String(q[0]);
  bq.className = 'qdo'; bq.lang = tl; bq.textContent = tx;
  au.className = 'qda'; au.textContent = '— ' + q[5];
  if (q[6]) au.title = q[6];
  cap.append(au); fig.append(bq, cap);
  return fig;
}
const qd_html = (/** @type {string} */ cls) => qd_node(cls).outerHTML;
// the placeholders drawn before this file was in (account.js qd_slot) get their line
function qd_fill() {
  for (const el of document.querySelectorAll('[data-qd]')) if (el instanceof HTMLElement) el.replaceWith(qd_node(el.dataset.qd || ''));
}
