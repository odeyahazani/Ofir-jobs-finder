export type JobRegion = "israel" | "abroad" | "unknown";

// Classify only the posting's location, never the company's address or job description.
// Missing, unrecognized and mixed locations stay available for manual review.
const israel = /(?:^|[^\p{L}\p{N}])(?:israel|ישראל|tel aviv(?: yafo)?|תל אביב(?: יפו)?|haifa|חיפה|caesarea|קיסריה|netanya|נתניה|yokn(?:e|ea|ea')am|yoqneam|yokne'?am|יקנעם|יקנעם עילית|herzliya|herzlia|הרצליה|binyamina|בנימינה|or akiva|אור עקיבא|jerusalem|ירושלים|rehovot|רחובות|petah tikva|petach tikva|פתח תקווה|ramat gan|רמת גן|hod hasharon|הוד השרון|kfar saba|כפר סבא|ra'?anana|רעננה|beer sheva|be'?er sheva|באר שבע|shoham|שוהם|ness ziona|נס ציונה|migdal haemek|migdal haemeq|מגדל העמק|tirat carmel|טירת כרמל|karmiel|כרמיאל|nahariya|נהריה|eilat|אילת|ashdod|אשדוד|ashkelon|אשקלון)(?=$|[^\p{L}\p{N}])/iu;
const abroad = /(?:^|[^\p{L}\p{N}])(?:united states(?: of america)?|u\.?s\.?(?:a\.?)?|ארצות הברית|united kingdom|u\.?k\.?|england|britain|europe|emea|apac|canada|germany|austria|switzerland|france|spain|italy|portugal|netherlands|poland|ireland|sweden|denmark|norway|finland|belgium|czechia|czech republic|romania|greece|india|china|taiwan|singapore|vietnam|japan|korea|australia|new zealand|brazil|mexico|argentina|south africa|turkey|united arab emirates|dubai|san jose|san francisco|san antonio|new york|chicago|washington|boston|seattle|austin|houston|dallas|atlanta|charlotte|charleston|brooklyn|queens|manhattan|long island|raleigh|buffalo grove|princeton|hoboken|lexington|california|texas|illinois|new jersey|north carolina|south carolina|kentucky|massachusetts|toronto|vancouver|london|berlin|munich|aachen|paris|beijing|shanghai|shanghai shi|taipei|bengaluru|bangalore|hyderabad|ahmedabad|ho chi minh city)(?=$|[^\p{L}\p{N}])/iu;

export function classifyLocation(value: string | null | undefined): JobRegion {
  const location = (value || "").normalize("NFKC").replace(/[־–—-]/g, " ").replace(/\s+/g, " ").trim();
  if (!location || /outside\s+israel|excluding\s+israel|not\s+(?:in\s+)?israel|מחוץ לישראל|ללא ישראל|\b(?:worldwide|global|anywhere|multiple locations|emea)\b|מספר מיקומים|כל העולם/i.test(location)) return "unknown";
  const inIsrael = israel.test(location);
  const outsideIsrael = abroad.test(location);
  if (inIsrael && !outsideIsrael) return "israel";
  if (outsideIsrael && !inIsrael) return "abroad";
  return "unknown";
}
