# MyServer — خادم الويب المتكامل لنظام أندرويد عبر Termux (الإصدار v2.22.0)

**بيئة تطوير واستضافة ويب محلية متكاملة (LEMP + Redis + أدوات إدارة) مُحسّنة خصيصاً لنظام أندرويد وتطبيق Termux.**

> 🌐 **اللغة / Language:** [🇬🇧 For English Click Here](./README.md)<br>📄 **سجل التغييرات:** [اضغط هنا لفتح سجل التحديثات](./CHANGELOG.md)

<br/>

&lt;p align=&quot;center&quot;&gt;
  &lt;img src=&quot;https://github.com/elias0esmail/termux-web-server/blob/main/Screenshot.jpg&quot; alt=&quot;MyServer Banner and Status&quot;/&gt;
&lt;/p&gt;
&lt;p align=&quot;center&quot;&gt;
  &lt;img src=&quot;https://github.com/elias0esmail/termux-web-server/blob/main/Screenshot1.jpg&quot; alt=&quot;MyServer Interactive Menu&quot;/&gt;
&lt;/p&gt;

<br/>

يقوم مشروع **MyServer** بتثبيت وإعداد وإدارة بيئة خادم ويب احترافية ومتكاملة لتطبيقات PHP على هواتف وأجهزة أندرويد باستخدام تطبيق **Termux**. يجمع المشروع بين **Nginx**، و**PHP-FPM**، و**MariaDB**، و**Redis**، ودعم شهادات **HTTPS/SSL**، ولوحة **phpMyAdmin**، ومدير المواقع المتعددة (**Virtual Hosts**)، وأداة إدارة قواعد البيانات من السطر (**Database CLI**)، وخادم التحديث التلقائي (**Live Reload**)، ونظام النسخ الاحتياطي الشامل، وأداة التشخيص الذاتي (**Doctor**)، مع إمكانية النشر المباشر للإنترنت عبر **Cloudflare Tunnel**؛ وكل ذلك داخل أداة تحكم واحدة خفيفة ومصممة خصيصاً لمراعاة قيود العمليات الفرعية في أندرويد.

> **سجل الإصدارات والتحديثات:** يمكنك الاطلاع على كافة الإصلاحات الأمنية والميزات الجديدة وتحسينات أندرويد عبر فتح ملف [CHANGELOG.md](./CHANGELOG.md).

## أبرز مميزات المشروع

- **خادم الويب Nginx:** مُعد مسبقاً للعمل عبر بروتوكول HTTP (منفذ `8080`) وبروتوكول HTTPS المشفر (منفذ `8443`) مع ضغط Gzip، وترويسات الأمان، وحماية ملفات أطر العمل الحساسة، ودعم المضيفات الافتراضية (`conf.d/*.conf`).
- **معالج PHP + PHP-FPM (بوضع `ondemand` الموفر للعمليات):** يأتي مفعّلاً بأهم الإضافات البرمجية (`mysqli`, `pdo_mysql`, `gd`, `sodium`, `redis`, `apcu`, `imagick`, `mbstring`, `curl`, `zip`, `intl`, `bcmath`) ومضبوطاً على وضع `pm = ondemand` بحيث لا يستهلك أي عملية فرعية خاملة في الخلفية عند عدم وجود طلبات.
- **قاعدة بيانات MariaDB:** مهيأة بنظام استيثاق آمن عبر المقبس المحلي (`Unix Socket`)، مع ميزة الإصلاح الذاتي لمشاكل الدخول (`unix_socket`) وضبط خاص لتقليل استهلاك الذاكرة العشوائية على الهواتف.
- **خادم التخزين المؤقت Redis:** مضبوط بحد أقصى للذاكرة (64 ميجابايت) مع كتم تحذيرات نواة `ARM64-COW-BUG`، وإمكانية تعطيله أو تفعيله بأمر واحد لتوفير العمليات الخلفية.
- **مدير المواقع المتعددة (`myserver site`):** استضافة عدة مشاريع مستقلة (Laravel أو WordPress أو Nextcloud أو PHP عادي) على منافذ مخصصة (`8081`، `8082`، إلخ) مع ضبط المسار الجذري وقواعد التوجيه تلقائياً.
- **إدارة قواعد البيانات من الطرفية (`myserver db`):** إنشاء وحذف واستيراد (`.sql`) وتصدير قواعد البيانات مباشرة من سطر الأوامر دون الحاجة لفتح المتصفح.
- **لوحة phpMyAdmin محمية محلياً:** متوفرة عبر الرابط `http://localhost:8080/phpmyadmin` مع حظر تلقائي (`HTTP 403 Forbidden`) لأي محاولة دخول قادمة من الإنترنت عبر نفق Cloudflare العام.
- **خادم التحديث التلقائي (Live Reload):** يقوم بتحديث صفحة المتصفح تلقائياً فور حفظ أي تعديل على ملفات المشروع باستخدام `inotifywait` مع تصفية أحداث الكتابة فقط ودعم ملف الاستثناءات `.myserver-ignore`.
- **النشر عبر الإنترنت (Cloudflare Tunnel):** مشاركة موقعك المحلي عبر رابط عام آمن `https://*.trycloudflare.com` بأمر واحد (`myserver internet-enable`) مع عزل تلقائي للوحات الإدارة.
- **النسخ الاحتياطي والاستعادة الشاملة:** أخذ لقطة كاملة تشمل ملفات المواقع (`htdocs`)، وقواعد البيانات، وشهادات SSL، والمضيفات الافتراضية، وملفات الإعداد في أرشيف `.tar.gz` واحد مع نسخ احتياطي وقائي قبل كل استعادة.
- **الفحص والتشخيص الذاتي (`myserver doctor`):** يفحص 38 عنصراً تشمل الحزم، إضافات PHP، الصلاحيات، المنافذ، قاعدة البيانات، الشهادات، الاتصال بالإنترنت، وعداد العمليات الفرعية في أندرويد (`X/32`) مع خيار الإصلاح التلقائي `--fix`.
- **مثبّت أطر العمل السريع (`myserver quickstart`):** تثبيت وإعداد كل من **WordPress** و**Laravel** و**Nextcloud** و**phpMyAdmin** بخطوة واحدة.

## 1. الخطوة الأولى: تحميل وتثبيت تطبيق Termux

قبل البدء بتثبيت الخادم، يجب تثبيت تطبيق **Termux** على هاتفك من مصدر رسمي ومحدّث.

> **تنبيه هام جداً:** **لا تقم** بتحميل تطبيق Termux من متجر Google Play؛ لأن النسخة الموجودة في متجر بلاي قديمة ومتوقفة ولا تعمل فيها مستودعات الحزم. قم دائماً بالتحميل من **إصدارات GitHub الرسمية** أو من متجر **F-Droid**.

### روابط التحميل الرسمية لتطبيق Termux والإضافات

| التطبيق | الوظيفة والأهمية | روابط التحميل الرسمية المباشرة |
| :--- | :--- | :--- |
| **Termux** *(أساسي ومطلوب)* | تطبيق الطرفية وبيئة لينكس الأساسية على أندرويد | • [**تحميل ملف APK من GitHub Releases**](https://github.com/termux/termux-app/releases)<br>• [**تحميل من متجر F-Droid الرسمي**](https://f-droid.org/en/packages/com.termux/) |
| **Termux:API** *(موصى به)* | يتيح ميزة `termux-wake-lock` لمنع أندرويد من إيقاف الخادم عند قفل الشاشة | • [**تحميل من GitHub Releases**](https://github.com/termux/termux-api/releases)<br>• [**تحميل من متجر F-Droid**](https://f-droid.org/en/packages/com.termux.api/) |
| **Termux:Boot** *(اختياري)* | لتشغيل خادم MyServer تلقائياً عند إعادة تشغيل الهاتف | • [**تحميل من GitHub Releases**](https://github.com/termux/termux-boot/releases)<br>• [**تحميل من متجر F-Droid**](https://f-droid.org/en/packages/com.termux.boot/) |

*ملاحظة لاختيار ملف APK المناسب من GitHub Releases:*
- معظم الهواتف الحديثة تعمل بمعمارية 64-بت، لذا اختر الملف الذي ينتهي بـ **`arm64-v8a.apk`**.
- إذا لم تكن متأكداً من نوع معالج هاتفك، قم بتحميل النسخة الشاملة **`universal.apk`**.
- احرص على تحميل Termux وإضافاته (Termux:API وTermux:Boot) من **نفس المصدر** (إما كلها من GitHub أو كلها من F-Droid) لتوافق التوقيع الرقمي.

### التهيئة الأولية لتطبيق Termux بعد التثبيت

بعد تثبيت تطبيق **Termux** وفتحه لأول مرة، نفّذ الخطوات الثلاث التالية:

1. **منح صلاحية الوصول لذاكرة الهاتف المشتركة:**
   ```bash
   termux-setup-storage
   ```
   اضغط على **سماح (Allow)** في نافذة الصلاحيات التي ستظهر على شاشة الهاتف.

2. **تحديث مستودعات وحزم النظام الأساسية:**
   ```bash
   pkg update -y && pkg upgrade -y
   ```
   *(إذا ظهر لك أي سؤال أثناء التحديث حول ملفات الإعداد، اضغط `Enter` لاختيار الإعداد الافتراضي).*

3. **إلغاء قيود توفير البطارية لتطبيق Termux:**
   ادخل إلى **إعدادات الهاتف (Settings) ← التطبيقات (Apps) ← Termux ← البطارية (Battery)** واختر **غير مقيد (Unrestricted)** لضمان عدم إغلاق الخادم في الخلفية.

## 2. الخطوة الثانية: تثبيت خادم MyServer من السيرفر

يمكنك تثبيت المشروع إما **بأمر واحد مباشرة من السيرفر** (الطريقة الأسرع والموصى بها) أو عبر **استنساخ المستودع يدوياً**.

### الطريقة الأولى: التثبيت المباشر بأمر واحد من السيرفر (موصى بها)

انسخ الأمر التالي والصقه داخل Termux ثم اضغط `Enter`:

```bash
curl -fsSL https://raw.githubusercontent.com/elias0esmail/termux-web-server/main/install.sh | bash
```

**ماذا يفعل هذا الأمر تلقائياً؟**
1. يتحقق من وجود الأدوات الأساسية (`curl` و`tar` و`python`) ويثبتها إن لم تكن موجودة.
2. يقوم بتنزيل أحدث نسخة من حزمة المشروع مباشرة من خادم GitHub إلى مجلد مؤقت.
3. يفك ضغط الحزمة ويشغل المثبّت الذكي `python install.py`.
4. ينظف الملفات المؤقتة تلقائياً بعد اكتمال التثبيت.

### الطريقة الثانية: التثبيت اليدوي عبر Git Clone

إذا كنت تفضل تنزيل المستودع والاحتفاظ بنسخة من الكود المصدري قبل التثبيت:

```bash
# 1. تحديث الحزم وتثبيت المتطلبات الأساسية
pkg update -y && pkg upgrade -y
pkg install -y python git curl

# 2. استنساخ المستودع من GitHub
git clone https://github.com/elias0esmail/termux-web-server.git
cd termux-web-server

# 3. تشغيل سكربت التثبيت
python install.py
```

### خيارات الإعداد التفاعلي أثناء التثبيت

أثناء التثبيت لأول مرة، سيسألك المثبّت سؤالين فقط:
1. **اختيار مكان مجلد المواقع (`htdocs`):**
   - **الخيار الأول — `Termux home` (`~/htdocs`):** يوفر أعلى سرعة وأفضل توافق مع صلاحيات لينكس `chmod` (موصى به لمشاريع Laravel وComposer).
   - **الخيار الثاني — `Phone storage` (`~/storage/shared/htdocs`):** يضع مجلد المواقع داخل الذاكرة المشتركة للهاتف لتتمكن من تعديل الملفات مباشرة من تطبيقات إدارة الملفات ومحررات الأكواد على أندرويد.
2. **كلمة مرور مسؤول قاعدة البيانات (`MariaDB root`):**
   - يمكنك إدخال كلمة مرور قوية (يتم حفظها تلقائياً وبأمان في `~/.my.cnf` بصلاحية `600`)، أو الضغط على `Enter` مباشرة لتركها بدون كلمة مرور لبيئة التطوير المحلية.

## 3. الخطوة الثالثة: تشغيل واستخدام الخادم

بعد انتهاء التثبيت، يمكنك فتح لوحة التحكم التفاعلية من أي مكان في Termux بكتابة:

```bash
myserver
```

أو تشغيل جميع خدمات الخادم مباشرة بالأمر:

```bash
myserver start
```

### الروابط والمنافذ الافتراضية للخادم

| الخدمة | الرابط / المنفذ الافتراضي | نطاق الوصول والملاحظات |
| :--- | :--- | :--- |
| **موقع الويب (HTTP)** | `http://localhost:8080` | رابط الخادم المحلي الأساسي |
| **رابط الشبكة المحلية (Wi-Fi)** | `http://<PHONE-LAN-IP>:8080` | لفتح موقعك من أي كمبيوتر أو هاتف آخر متصل بنفس شبكة الـ Wi-Fi (يظهر في `myserver status`) |
| **موقع الويب المشفر (HTTPS)** | `https://localhost:8443` | يعمل بشهادة SSL موقعة ذاتياً بشكل افتراضي (أو شهادة مخصصة عبر `ssl-import`) |
| **لوحة phpMyAdmin** | `http://localhost:8080/phpmyadmin` | **محلي فقط** — محمية تلقائياً وتُرجع `403 Forbidden` عند محاولة فتحها من نفق Cloudflare العام |
| **المواقع المتعددة (VHosts)** | `http://localhost:8081+` | منافذ مستقلة للمشاريع المضافة عبر أداة `myserver site add` |
| **معالج PHP-FPM** | `127.0.0.1:9000` | منفذ FastCGI داخلي (`ondemand` بحد أقصى 4 عمال) |
| **قاعدة بيانات MariaDB** | `$PREFIX/var/run/mysqld/mysqld.sock` | مقبس محلي سريع + المنفذ `127.0.0.1:3306` |
| **خادم Redis** | `127.0.0.1:6379` | خادم التخزين المؤقت المحلي (بحد أقصى 64 ميجابايت) |
| **خادم Live Reload** | `127.0.0.1:35730` | خادم التحديث التلقائي للمتصفح عبر SSE |

## 4. نظرة عامة على القائمة التفاعلية (`myserver`)

عند تشغيل الأمر `myserver` بدون معاملات، تفتح لك واجهة تفاعلية ذكية تتكيف مع حالة الخادم:

- **عندما يكون الخادم متوقفاً:** تتيح لك تشغيل الخدمات (`start`)، تحديث الحالة (`refresh`)، استعراض النسخ الاحتياطية (`backup-list`)، استعادة نسخة احتياطية (`restore`)، فحص البيئة (`doctor`)، عرض تفاصيل شهادة SSL (`ssl-info`)، التحقق من التحديثات (`update`)، إعادة التثبيت مع حفظ البيانات (`reinstall`)، أو الحذف الكامل (`uninstall`).
- **عندما يكون الخادم قيد التشغيل:** تعرض لك حالة كل خدمة مع استهلاك الذاكرة (`MB`) وعداد عمليات أندرويد (`Processes: X/32`)، وتتيح لك إيقاف الخادم، تفعيل/تعطيل **Live Reload**، تفعيل/تعطيل **النشر عبر الإنترنت (Cloudflare Tunnel)**، تثبيت أطر العمل (**Quickstart**)، إدارة **المواقع المتعددة (`sites`)**، إدارة **قواعد البيانات (`db`)**، أخذ نسخة احتياطية، فحص الأعطال، أو قراءة السجلات (`logs`).

## 5. دليل الأوامر الشامل (Command Reference)

يمكنك عرض قائمة الأوامر في أي وقت عبر تنفيذ `myserver help`.

### أ. التحكم بالخدمات وتوفير العمليات

```bash
myserver start           # تشغيل جميع الخدمات المفعّلة
myserver stop            # إيقاف جميع الخدمات بأمان وتحرير قفل الشاشة
myserver restart         # إعادة تشغيل جميع الخدمات
myserver status          # عرض حالة الخدمات، الذاكرة، عنوان Wi-Fi، وعداد عمليات أندرويد
myserver redis-disable   # تعطيل خدمة Redis لتوفير عملية خلفية إضافية في أندرويد
myserver redis-enable    # إعادة تفعيل وتشغيل خدمة Redis
```

### ب. إدارة المواقع المتعددة (Virtual Hosts / Multi-Site)

استضف عدة مشاريع مستقلة على منافذ محلية مخصصة دون الحاجة لتعديل ملفات Nginx يدوياً:

```bash
# عرض جميع المواقع الافتراضية المضافة
myserver site list

# إضافة مشروع Laravel على المنفذ 8081 (يوجه الجذر تلقائياً إلى مجلد public)
myserver site add myapp ~/htdocs/myapp --port 8081 --type laravel

# إضافة موقع WordPress أو PHP (يختار أول منفذ متاح تلقائياً بدءاً من 8081)
myserver site add blog ~/htdocs/blog --type wordpress

# حذف إعداد الموقع الافتراضي (مع بقاء ملفات المشروع سليمة في htdocs)
myserver site remove myapp
```

### ج. إدارة قواعد البيانات من السطر (`myserver db`)

```bash
myserver db list                        # عرض جميع قواعد بيانات المستخدم
myserver db create shop_db              # إنشاء قاعدة بيانات جديدة بترميز utf8mb4
myserver db import shop_db schema.sql   # استيراد ملف SQL إلى قاعدة البيانات
myserver db export shop_db backup.sql   # تصدير قاعدة البيانات إلى ملف SQL
myserver db drop shop_db                # حذف قاعدة بيانات (مع طلب التأكيد)
```

### د. المثبّت السريع لأطر العمل (`myserver quickstart`)

```bash
myserver quickstart
```

يفتح قائمة تفاعلية لتنزيل وإعداد كل من:
1. **WordPress** (`http://localhost:8080/wordpress`)
2. **Laravel** (`http://localhost:8080/<name>/public` + إنشاء مضيف افتراضي VHost مستقل تلقائياً)
3. **Nextcloud** (إنشاء قاعدة بيانات وحساب مخصص + مضيف افتراضي بقواعد CalDAV/CardDAV)
4. **phpMyAdmin** (تثبيت جديد أو تحديث مع الحفاظ على ملف `config.inc.php`)

### هـ. التحديث التلقائي للمتصفح (Live Reload)

```bash
myserver live-start      # تشغيل مراقب الملفات وتفعيل التحديث التلقائي للمتصفح
myserver live-stop       # إيقاف التحديث التلقائي
myserver live-restart    # إعادة تشغيل خدمة التحديث التلقائي
myserver live-status     # عرض حالة المراقب وملف العلامة .livereload
myserver live-toggle     # تبديل الحالة (تشغيل / إيقاف)
```

### و. النشر للإنترنت عبر Cloudflare Tunnel

```bash
myserver internet-enable
myserver internet-disable
```

- ينشئ نفقاً آمناً عبر `cloudflared` ويعطيك رابطاً عاماً `https://*.trycloudflare.com`.
- **حماية تلقائية للوحة الإدارة:** يقوم Nginx تلقائياً بحظر أي طلب قادم عبر نفق Cloudflare (يحمل ترويسة `CF-Connecting-IP`) من الوصول إلى `/phpmyadmin` أو `/phpinfo` وإرجاع `403 Forbidden`، لضمان بقاء قواعد بياناتك في مأمن تام.

### ز. النسخ الاحتياطي والاستعادة الشاملة

```bash
myserver backup                # إنشاء نسخة احتياطية مؤرخة تلقائياً
myserver backup my-snapshot    # إنشاء نسخة احتياطية باسم مخصص
myserver backup-list           # عرض قائمة النسخ الاحتياطية المتوفرة وأحجامها
myserver restore               # فتح قائمة تفاعلية لاختيار واستعادة نسخة احتياطية
myserver restore /path/to/file.tar.gz
```

### ح. إدارة شهادات SSL والتشخيص والسجلات والصيانة

```bash
myserver ssl-info                            # عرض تفاصيل شهادة SSL وصلاحيتها وبصمة SHA-256
myserver ssl-import /path/cert.pem /path/key.pem   # استيراد شهادة SSL ومفتاح خاص مخصصين
myserver ssl-remove                          # إزالة الشهادة المخصصة والعودة للشهادة الذاتية
myserver doctor                              # فحص شامل للبيئة والعمليات (38 فحصاً)
myserver doctor --fix                        # إصلاح تلقائي للإضافات الناقصة والصلاحيات
myserver logs <nginx|php|redis|live|tunnel>  # عرض آخر سطور السجلات لأي خدمة
myserver wake-lock                           # تفعيل قفل منع السكون
myserver wake-unlock                         # إلغاء قفل منع السكون
myserver wake-status                         # عرض حالة القفل وتطبيق Termux:Boot
myserver update                              # فحص وتثبيت أحدث إصدار من GitHub
myserver reinstall                           # إعادة التثبيت مع الحفاظ على قواعد البيانات والمواقع
myserver uninstall                           # حذف الخادم بالكامل (يتطلب كتابة yes للتأكيد)
```

## 6. تحسينات ضوابط العمليات الفرعية في أندرويد 12+ (Phantom Process Killer)

تفرض أنظمة Android 12 و13 و14 وما بعدها قيداً صارماً يسمح بحد أقصى قدره **32 عملية فرعية (Phantom Processes)** للتطبيقات التي تعمل في الخلفية. عند تجاوز هذا الحد، يقوم أندرويد بقتل العمليات فوراً بالرسالة `[Process completed (signal 9)]`.

### كيف يحميك الإصدار `v2.22.0` من الإغلاق القسري؟

1. **وضع `ondemand` في PHP-FPM:** بدلاً من إبقاء 3 إلى 10 عمليات PHP مفتوحة طوال الوقت، يعمل PHP-FPM بعملية رئيسية واحدة فقط عند السكون (`0` عمليات فرعية خاملة)، وينشئ حتى 4 عمال فقط عند وصول طلبات فعلية ثم يغلقهم بعد 10 ثوانٍ من الخمول.
2. **عامل واحد لـ Nginx وتشغيل مباشر لـ `mariadbd`:** يعمل Nginx بعامل واحد (`worker_processes 1;`)، ويتم تشغيل `mariadbd` مباشرة بدون سكربت الغلاف `mariadbd-safe` مع تعطيل `performance_schema`.
3. **الفحص المباشر عبر `/proc` بدون عمليات فرعية:** يتم فحص حالة الخدمات، واستهلاك الذاكرة، والاتصال بالإنترنت، وعنوان IP المحلي بلغة Python الصرفة دون استدعاء أوامر خارجية مثل `pgrep` أو `pkill` أو `curl` أو `/bin/sh`.
4. **إمكانية تعطيل Redis (`myserver redis-disable`):** لتوفير عملية إضافية عندما لا يحتاج مشروعك إلى Redis.

### خيار متقدم: إلغاء قيد الـ 32 عملية في أندرويد عبر ADB

إذا كنت تشغل أدوات ثقيلة بجانب الخادم (مثل Composer أو Node.js أو جلسات SSH متعددة)، يمكنك رفع سقف العمليات في أندرويد 12+ عبر أداة **ADB** أو تطبيق **LADB / Shizuku** بالأوامر التالية:

```bash
adb shell "/system/bin/device_config set_sync_disabled_for_tests persistent"
adb shell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"
adb shell settings put global settings_enable_monitor_phantom_procs false
```

## 7. معلومات المطور والروابط

- **المطور:** إلياس إسماعيل (Elias M. Esmail)
- **حساب GitHub:** [elias0esmail](https://github.com/elias0esmail)
- **مستودع المشروع:** [termux-web-server](https://github.com/elias0esmail/termux-web-server)
- **الدليل باللغة الإنجليزية:** [README.md (English Documentation)](./README.md)
- **سجل التغييرات والإصدارات:** [CHANGELOG.md](./CHANGELOG.md)
- **الإبلاغ عن المشاكل والاقتراحات:** [https://github.com/elias0esmail/termux-web-server/issues](https://github.com/elias0esmail/termux-web-server/issues)
- **واتساب:** `+967771902342`

## الترخيص (License)

هذا المشروع مرخص تحت رخصة [MIT License](./LICENSE).
