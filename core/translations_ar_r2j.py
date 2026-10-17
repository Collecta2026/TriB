"""Arabic text for remittance advice (print and email after paying suppliers) and customer statements (open items,
ageing to over 120 days, email and batch statements). Merged into core.translations_ar.AR."""

AR2J = {
    "%(n)s customer{% plural %}%(n)s customers": "%(n)s عميل",
    "%(n)s payment{% plural %}%(n)s payments": "%(n)s دفعة",
    "%(n)s statements sent.": "تم إرسال %(n)s كشف حساب.",
    "%(n)s statement{% plural %}%(n)s statements": "%(n)s كشف حساب",
    "91–120 days": "91–120 يومًا",
    "Over 120 days": "أكثر من 120 يومًا",
    "Balance forward only: the start of the period.": "لكشف الرصيد المرحّل فقط: بداية الفترة.",
    "Balance forward: every transaction in the period": "رصيد مرحّل: كل الحركات خلال الفترة",
    "Open items: unpaid invoices with their age": "البنود المفتوحة: الفواتير غير المسددة وأعمارها",
    "Balances are in your base currency; each statement is in the customer's own currency.":
        "الأرصدة بعملتك الأساسية؛ وكل كشف حساب بعملة العميل نفسه.",
    "Batch statements": "كشوف حساب مجمّعة",
    "Choose at least one payment.": "اختر دفعة واحدة على الأقل.",
    "Choose payments to one supplier at a time.": "اختر مدفوعات مورد واحد في كل مرة.",
    "Choose the customer and dates first.": "اختر العميل والتواريخ أولًا.",
    "Could not be sent: %(names)s": "تعذر الإرسال إلى: %(names)s",
    "Credit note not yet used": "إشعار دائن لم يُستخدم بعد",
    "Payments not yet applied to an invoice": "مدفوعات لم تُخصم من فاتورة بعد",
    "Email %(n)s customer{% plural %}Email %(n)s customers": "إرسال بالبريد إلى %(n)s عميل",
    "Email %(n)s statement now?{% plural %}Email %(n)s statements now?": "إرسال %(n)s كشف حساب بالبريد الآن؟",
    "Email isn't set up yet, so TriB can't send it for you. Print it or save it as PDF instead. Your administrator "
    "can add the email account in Render (EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD).":
        "البريد الإلكتروني غير مُعد بعد، لذلك لا يستطيع TriB إرساله نيابة عنك. اطبعه أو احفظه PDF بدلًا من ذلك. يمكن "
        "للمسؤول إضافة حساب البريد في Render ‏(EMAIL_HOST وEMAIL_HOST_USER وEMAIL_HOST_PASSWORD).",
    "Email isn't set up yet, so TriB can't send statements. Print them instead.":
        "البريد الإلكتروني غير مُعد بعد، لذلك لا يستطيع TriB إرسال كشوف الحساب. اطبعها بدلًا من ذلك.",
    "Email remittance advice (selected payments)": "إرسال إشعارات السداد بالبريد (المدفوعات المحددة)",
    "Email to customer": "إرسال للعميل بالبريد",
    "Email to supplier": "إرسال للمورد بالبريد",
    "Every customer with a balance": "كل عميل عليه رصيد",
    "Only customers with overdue invoices": "العملاء الذين لديهم فواتير متأخرة فقط",
    "No email address": "لا يوجد بريد إلكتروني",
    "No email address, so not sent: %(names)s": "لم يُرسل لعدم وجود بريد إلكتروني: %(names)s",
    "No payments to show.": "لا توجد مدفوعات لعرضها.",
    "Payment recorded. Print the remittance advice or email it to the supplier.":
        "تم تسجيل الدفعة. اطبع إشعار السداد أو أرسله للمورد بالبريد.",
    "Print all": "طباعة الكل",
    "Remittance advice %(number)s from %(company)s": "إشعار سداد %(number)s من %(company)s",
    "Remittance advice for %(n)s payments from %(company)s": "إشعار سداد عن %(n)s دفعات من %(company)s",
    "Select one or more payments first.": "حدد دفعة أو أكثر أولًا.",
    "Sent to %(to)s.": "تم الإرسال إلى %(to)s.",
    "Show customers": "عرض العملاء",
    "Statement date": "تاريخ الكشف",
    "Statement of account from %(company)s": "كشف حساب من %(company)s",
    "Statement type": "نوع الكشف",
    "Statements for all your customers at once: print them, or email each customer their own.":
        "كشوف حساب لكل عملائك مرة واحدة: اطبعها، أو أرسل لكل عميل كشفه بالبريد.",
    "The email contains the remittance advice itself, so your supplier can read it without signing in.":
        "يحتوي البريد على إشعار السداد نفسه، فيستطيع المورد قراءته دون تسجيل الدخول.",
    "The email contains the statement itself, so your customer can read it without signing in.":
        "يحتوي البريد على كشف الحساب نفسه، فيستطيع العميل قراءته دون تسجيل الدخول.",
    "Dear %(name)s,\n\nWe have paid %(amount)s %(cur)s on %(date)s. The details of the invoices this payment covers "
    "are below.\n\nKind regards,\n%(company)s":
        "السادة %(name)s،\n\nقمنا بسداد %(amount)s %(cur)s بتاريخ %(date)s. تفاصيل الفواتير التي تغطيها هذه الدفعة "
        "أدناه.\n\nمع خالص التحية،\n%(company)s",
    "Dear %(name)s,\n\nPlease find below our remittance advice for payments %(numbers)s, %(amount)s in total. Each "
    "shows the invoices it covers.\n\nKind regards,\n%(company)s":
        "السادة %(name)s،\n\nنرفق أدناه إشعارات السداد للمدفوعات %(numbers)s بإجمالي %(amount)s. يوضح كل إشعار "
        "الفواتير التي يغطيها.\n\nمع خالص التحية،\n%(company)s",
    "Dear %(name)s,\n\nPlease find below your statement of account to %(date)s. The balance is %(amount)s "
    "%(cur)s.\n\nPlease let us know within 15 days if it does not agree with your records.\n\nKind regards,\n"
    "%(company)s":
        "السادة %(name)s،\n\nنرفق أدناه كشف حسابكم حتى %(date)s. الرصيد %(amount)s %(cur)s.\n\nيرجى إخطارنا خلال "
        "15 يومًا في حال عدم مطابقته لسجلاتكم.\n\nمع خالص التحية،\n%(company)s",
    # Older strings split over several lines, found by the AST check in tests/test_i18n.py.
    "Dear %(name)s,\n\nPlease find %(doc)s %(number)s for %(amount)s %(cur)s. You can view and print it using the "
    "link below.\n\nThank you for your business.\n%(company)s":
        "السيد/السيدة %(name)s،\n\nمرفق %(doc)s رقم %(number)s بمبلغ %(amount)s %(cur)s. يمكنك عرضه وطباعته من "
        "الرابط أدناه.\n\nشكرًا لتعاملكم معنا.\n%(company)s",
    "%(sku)s: extra stock was counted but no batch is known. Enter it with a stock adjustment showing its batch and "
    "expiry date.":
        "%(sku)s: تم جرد كمية زائدة دون معرفة التشغيلة. أدخلها بتسوية مخزون مع رقم التشغيلة وتاريخ الصلاحية.",
    "Not enough stock of %(sku)s in %(wh)s: %(have)s in date, %(need)s needed (%(exp)s more is expired and cannot "
    "be sold).":
        "لا يوجد مخزون كافٍ من %(sku)s في %(wh)s: المتاح الصالح %(have)s والمطلوب %(need)s (و%(exp)s أخرى منتهية "
        "الصلاحية ولا يمكن بيعها).",
}
