# פריסה ב־Vercel ו־Supabase

הקוד תומך כעת באחסון קבוע ב־Supabase, לצד SQLite לפיתוח מקומי. בדיקת SQL מקומית אינה אימות של פרויקט Supabase החיצוני. יש להשלים את ההגדרות ולבדוק כניסה אמיתית לפני הפעלה קבועה.

## הקמת מסד הנתונים

1. פתחו את `supabase/setup.sql` ב־GitHub, בתצוגת Raw, והעתיקו את כל הקובץ ל־SQL Editor של פרויקט Supabase הנכון.
2. בתחילת הקובץ החליפו את `REPLACE_WITH_OFIR_GOOGLE_EMAIL` בכתובת ה־Google של אופיר, בתוך הגרשיים. זהו המקום היחיד להחלפה. הכתובת צריכה להיות זהה ל־`OFIR_ALLOWED_EMAIL`.
3. הריצו את הקובץ כולו. הוא יוצר טבלאות, הרשאות, רשימת חשבון יחיד וזרע של 138 חברות. הוא רץ בעסקה אחת ונכשל אם לא הוזנה כתובת תקינה. אפשר להריצו שוב עם אותו מייל בלי למחוק משרות או סימונים.
4. בדקו ב־Table Editor שמופיעות 138 חברות וש־RLS מופעל על הטבלאות. החשבון המורשה יכול לקרוא משרות ולשנות רק סימונים אישיים. משתמש אחר אינו מקבל שורות, ולמשתמש אנונימי אין הרשאת קריאה.

## Vercel

ייבאו את הריפו הפרטי `Ofir-jobs-finder` כפרויקט Next.js, בענף main, עם Node 24. הגדירו ב־Environment Variables:

| שם | ערך |
|---|---|
| `OFIR_STORAGE` | `supabase` |
| `LOCAL_DEV_MODE` | `0` |
| `NEXT_PUBLIC_SUPABASE_URL` | כתובת פרויקט Supabase |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | המפתח הציבורי של הפרויקט |
| `OFIR_ALLOWED_EMAIL` | חשבון ה־Google של אופיר, כמו בקובץ ההקמה |
| `APP_URL` | כתובת ה־HTTPS הקבועה של האתר ב־Vercel, בלי לוכסן בסוף |

לאתר אין צורך במפתח service_role, במפתח טלגרם או בסיסמת מסד נתונים. משתמשים בהרשאות המשתמש שהתחבר וב־RLS; אין עקיפת הרשאות באמצעות מפתח מנהל בשרת האתר. השלימו את המשתנים לפני בדיקת הכניסה. אם הכתובת התבררה רק אחרי הפריסה הראשונה, עדכנו `APP_URL` ובצעו Redeploy. שינוי משתני NEXT_PUBLIC דורש בנייה מחדש.

ב־Supabase, תחת Authentication → URL Configuration:

- Site URL: כתובת האתר הקבועה.
- Redirect URLs: אותה כתובת עם `/auth/callback` בסוף, בדיוק.

הכתובת שהוגדרה אצל Google נשארת כתובת Supabase עם `/auth/v1/callback`. יש שני שלבי חזרה שונים: Google מחזיר ל־Supabase, ו־Supabase מחזיר לאתר.

בדקו כניסה אמיתית של אופיר ושמירת סימון אחרי רענון; נסו חשבון אחר וודאו שהוא נדחה. הפעילו ב־Google משתמשי בדיקה מתאימים אם האפליקציה עדיין במצב Testing. אימות Google נשאר צורך חיצוני שלא אומת בבדיקות המקומיות.

## אוכלוסיית משרות וסריקות

קובץ ההקמה מייבא חברות בלבד. כדי לשמור גם את 265 הרשומות וההיסטוריה שכבר נאספו, ניתן להעביר את מסד הנתונים המקומי לאחר הקמת הטבלאות:

```bash
python -m collector.cloud check
python -m collector.cloud migrate --sqlite .local/ofir.sqlite
python -m collector.cloud scan
```

הפקודות זקוקות ל־`NEXT_PUBLIC_SUPABASE_URL` ול־`SUPABASE_SERVICE_ROLE_KEY` בהגדרות סודיות של המחשב שמריץ את האיסוף. מפתח זה נועד לאיסוף בלבד, אינו נשלח לדפדפן ואינו נדרש ב־Vercel. השתמשו במפתח service_role מסוג JWT מהגדרות ה־API של Supabase. אין להדביקו לצ׳אט או לקוד. הגישה ברשת צריכה לאפשר HTTPS לדומיין הפרויקט ולמקורות המשרות.

העברת הנתונים אינה מוחקת את המקור. העברה חוזרת משמרת סימונים שכבר קיימים בענן, אינה מאפסת התראות שנשלחו ואינה משכפלת אירועי משרה. המשיכו לעבוד בגרסה אחת אחרי המעבר: סימונים שייעשו מאוחר יותר במסד המקומי לא ידרסו במכוון סימונים קיימים בענן.

## GitHub Actions

קיים workflow בשם **Job collector**, עם הפעלה ידנית ותזמון מותנה. הפעילו רק אחרי הגדרת Repository Settings → Secrets and variables → Actions:

- Variables: `NEXT_PUBLIC_SUPABASE_URL`, `APP_URL`.
- Secrets: `SUPABASE_SERVICE_ROLE_KEY`; להודעות גם `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

Actions → Job collector → Run workflow מאפשר check, scan ותצוגה מקדימה של סיכום. `digest-send` שולח הודעה אמיתית. טבלאות Supabase שומרות את מצב ההתראות גם בין מחשבים והרצות. מפתח service_role נותן הרשאות מנהל לאיסוף ולכן נשמר כסוד ב־Actions בלבד. תהליכי האיסוף מסודרים בקבוצת concurrency משותפת; אל תריצו איסוף ידני ממחשב אחר במקביל ל־Actions.

**תזמון סריקות זמין אך נשאר כבוי כל עוד `ENABLE_SCHEDULED_SCANS` לא הוגדר ל־`true`.** הוראות ההפעלה וההרחבה נמצאות ב־`docs/growth-setup.he.md`. הודעות טלגרם אינן מופעלות על ידי תזמון הסריקות. Vercel מארח את האתר; הוא אינו מריץ את Python פעמיים ביום. אפשר להישאר במסלולים חינמיים בהתאם למכסות התקפות של Vercel, Supabase ו־GitHub Actions; אין התחייבות להיעדר עלויות מעבר למכסות.

לייבוא מועמדויות לענן:

```bash
python -m collector.cloud import-applications /path/to/applications.csv
```

אותו פורמט CSV ואותה מניעת כפילויות כמו בייבוא המקומי. ייבוא היסטוריה יתבצע לפני הפעלת הודעות שוטפות.


## איסוף מתוזמן ושחזור תקלות

ראו [תזמון, מיגרציה, בדיקות ופריסה בטוחה](scheduled-collection.he.md). השינוי דורש את `supabase/upgrade-scheduling.sql` לפני פריסת העובד. אין להחיל `setup.sql` מחדש על פרויקט קיים או להפעיל תזמון לפני בדיקה ואישור נפרדים.
