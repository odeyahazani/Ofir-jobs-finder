"""Conservative posting geography; company addresses are never location evidence."""
import re
import unicodedata

ISRAEL = re.compile("(?:^|[^\\w])(?:israel|ישראל|tel aviv(?: yafo)?|תל אביב(?: יפו)?|haifa|חיפה|caesarea|קיסריה|netanya|נתניה|yokn(?:e|ea|ea')am|yoqneam|yokne'?am|יקנעם|יקנעם עילית|herzliya|herzlia|הרצליה|binyamina|בנימינה|or akiva|אור עקיבא|jerusalem|ירושלים|rehovot|רחובות|petah tikva|petach tikva|פתח תקווה|ramat gan|רמת גן|hod hasharon|הוד השרון|kfar saba|כפר סבא|ra'?anana|רעננה|beer sheva|be'?er sheva|באר שבע|shoham|שוהם|ness ziona|נס ציונה|migdal haemek|migdal haemeq|מגדל העמק|tirat carmel|טירת כרמל|karmiel|כרמיאל|nahariya|נהריה|eilat|אילת|ashdod|אשדוד|ashkelon|אשקלון)(?=$|[^\\w])", re.I)
ABROAD = re.compile('(?:^|[^\\w])(?:united states(?: of america)?|u\\.?s\\.?(?:a\\.?)?|ארצות הברית|united kingdom|u\\.?k\\.?|england|britain|europe|emea|apac|canada|germany|austria|switzerland|france|spain|italy|portugal|netherlands|poland|ireland|sweden|denmark|norway|finland|belgium|czechia|czech republic|romania|greece|india|china|taiwan|singapore|vietnam|japan|korea|australia|new zealand|brazil|mexico|argentina|south africa|turkey|united arab emirates|dubai|san jose|san francisco|san antonio|new york|chicago|washington|boston|seattle|austin|houston|dallas|atlanta|charlotte|charleston|brooklyn|queens|manhattan|long island|raleigh|buffalo grove|princeton|hoboken|lexington|california|texas|illinois|new jersey|north carolina|south carolina|kentucky|massachusetts|toronto|vancouver|london|berlin|munich|aachen|paris|beijing|shanghai|shanghai shi|taipei|bengaluru|bangalore|hyderabad|ahmedabad|ho chi minh city)(?=$|[^\\w])', re.I)


def in_israel(value):
    location = re.sub(r'\s+', ' ', re.sub('[־–—-]', ' ', unicodedata.normalize('NFKC', value or ''))).strip()
    if re.search(r'outside\s+israel|excluding\s+israel|not\s+(?:in\s+)?israel|מחוץ לישראל|ללא ישראל|\b(?:worldwide|global|anywhere|multiple locations|emea)\b|מספר מיקומים|כל העולם', location, re.I):
        return False
    return bool(ISRAEL.search(location)) and not ABROAD.search(location)
