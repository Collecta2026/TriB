"""TriB user manual, English. Each topic: (key, section key, title, page prefixes it explains, body).

Body markup (rendered by core.help.render): blank line = new paragraph; "- " bullet; "1. " numbered step;
"**text**" bold; "Tip: ..." a tip box; "Note: ..." a note box. Arabic is in help_ar.py under the same keys."""

SECTIONS = [
    ("start", "Getting started"),
    ("sales", "Sales and customers"),
    ("purchases", "Purchases and suppliers"),
    ("banking", "Banking and cheques"),
    ("accounting", "Accounting"),
    ("inventory", "Inventory"),
    ("assets", "Fixed assets"),
    ("payroll", "Team and payroll"),
    ("crm", "Customer Hub (CRM)"),
    ("reports", "Reports and planning"),
    ("faster", "Working faster"),
    ("data", "Your data, settings and privacy"),
]

TOPICS = [
    # ---------------- Getting started ----------------
    ("welcome", "start", "Welcome to TriB", [], """
TriB is a bilingual (English and Arabic) accounting and business system for companies in Egypt and the Middle East. It keeps your books, sales, purchases, stock, cheques, fixed assets, payroll and customer relationships in one place, and every number on the screen comes straight from the ledger.

This manual explains every screen. Use the search box at the top of the Help centre, or open **Help for this page** from the **?** menu at the top right of any screen.

- Every document you post creates its journal entry automatically.
- Everything is recorded in the audit log: who did what, and when.
- What each person can see and do is set by their role.
"""),
    ("sign-in", "start", "Signing in, language and password", ["/accounts/"], """
1. Open TriB in your browser and sign in with your email and password.
2. Switch between **English** and **عربي** with the language button at the top right. The whole screen, including the layout direction, changes.
3. To change your password, open your initials (top right) and choose **Change password**.

Note: For security you are signed out when you close the browser, and after 10 hours at most.
"""),
    ("screen", "start", "Finding your way around", [], """
**The menu on the left (rail)**
- **Create** opens the list of everything you can create: invoices, bills, cheques, journals and more.
- **Bookmarks** holds the pages you use most.
- **Home**, **Reports** and **All apps** take you to the dashboard, the reports page and every app.
- **Pinned** apps show their pages when you point at them. Each page has a bookmark icon to add it to Bookmarks.

**The bar at the top**
- Search finds vouchers, accounts and cheques by number or name.
- The star bookmarks the page you are on.
- **?** opens Help, the bell shows Alerts, the gear opens Settings, and your initials hold your account.

Tip: Menus open when you point at them. On a touch screen, tap instead.
"""),
    ("dashboard", "start", "The dashboard", ["/"], """
The home page shows the health of the business at a glance.

- **App shortcuts** under the greeting take you straight to each app. Use the arrows to see more.
- **Business feed** shows what needs attention as tiles: approvals waiting for you (approve them right there), overdue invoices, bills to pay, cheques due, stock expiry, tasks and appointments, and cash falling below your minimum. **View all** opens every alert.
- **Create actions** are one-click shortcuts. **Show all** reveals the rest.
- **Business at a glance** holds the widgets: cash flow, profit and loss, bank accounts, invoices, expenses, receivables, payables, sales, customer orders, stock alerts and post-dated cheques.

Every number, tile, bar and row opens the list or report behind it. For example, select the **Overdue** tile in Invoices to see exactly which invoices are overdue.

**Privacy** blurs the amounts when others can see your screen.
"""),
    ("customise-dashboard", "start", "Customising your dashboard", ["/"], """
1. On the home page select **Customise**, next to Privacy.
2. **Add widgets**: tick the widgets you want and untick the ones you don't. You can also hide a widget with **×**.
3. **Move** a widget by dragging its handle (top corner) to a new place.
4. **Resize** a widget by dragging the corner at its bottom edge to make it one to four columns wide.
5. Select **Save**. **Reset layout** goes back to the standard layout.

Note: Your layout is saved for you only. Each user arranges their own dashboard.
"""),
    ("settings", "start", "Settings and company details", ["/settings/", "/lists/", "/subscription/"], """
Open the **gear** at the top right. Settings is arranged in four columns:

- **Your company**: Account and settings (name, tax numbers, currencies, exchange rates, lock date, approval behaviour, minimum cash balance), Manage users, Default report settings, Chart of accounts, Additional info and My accountant.
- **Lists**: All lists, Products and services, Recurring transactions, Attachments and Rules.
- **Tools**: Reconcile and Audit log.
- **Profile**: Subscriptions and billing, Feedback, Privacy and Cookies.

Items marked "soon" are planned and not yet available.

Tip: Set the **lock date** after closing a month. Nothing can then be posted on or before that date.
"""),
    ("users", "start", "Users, roles and approval limits", ["/accounts/users/", "/accounts/roles/", "/settings/accountant/"], """
1. Open the gear and choose **Manage users**, then **+ Add user**.
2. Enter the full name, email (used to sign in), language and a temporary password of at least 10 characters.
3. Tick one or more **roles**, for example Accountant, Cashier, Sales officer, Purchasing officer, Storekeeper, HR officer or Managing director.
4. Leave **Branches** and **Warehouses** empty to allow all of them, or tick the ones this person works in. Then **Save**.

Select a role's name to change it. The **authority matrix** has one row per module and these columns:

- **View, Create, Edit**: open, add and change records.
- **Delete drafts**: delete a draft invoice, bill, order or payroll run. Posted documents are voided, never deleted.
- **Approve, Authorise, Post, Void, Export**: as their names say.
- **See costs & margins** (Inventory): purchase costs, stock values, gross margin and the valuation reports. Without it, staff see quantities and selling prices only.

**Own records only**: tick it on a role (for example Sales officer) and its people see only the customers they look after (the customer's **Account manager**), their own leads and opportunities, and the sales documents for those customers. Customers they add are theirs automatically. A person sees everything as soon as one of their roles is not limited.

**Warehouses**: a person limited to some warehouses sees stock, movements, transfers, adjustments, stock takes, item receipts and orders for those warehouses only, and can only pick those. Transfers may still send stock to any warehouse.

**Approval limits** (amounts in your base currency) are set per role and per document: receipt, payment (expenses) and journal vouchers, **purchase orders** and **bills**.

- A purchase order above an approver's limit can be **approved at their level**. It then goes to someone whose limit covers it, and is approved when they approve it. Every approval is listed on the order.
- A bill above the poster's limit is **sent for approval** instead of posted, and someone whose bill limit covers it posts it.
- Waiting orders and bills appear in **Approvals → Waiting for me**, the Approvals card in the business feed and the bell.
- An empty limit means the role cannot approve that document; 999999999999 means no limit.

**Who can do what** (Users & roles, or Reports → For my accountant) lists every person's roles, branches, warehouses, record scope, limits and permissions, and each role's matrix. Print it or export it to Excel for review and sign-off.

**My accountant** invites your outside accountant with the Accountant role already ticked.

To remove access, open the user and untick **Active**. Their history stays in the audit log.

Tip: Give the person who raises purchase orders (for example Logistics) the Purchasing officer and Storekeeper roles, limited to their warehouse, and give the managers who approve them a purchase order limit.
"""),

    # ---------------- Sales ----------------
    ("customers", "sales", "Customers and the customer page", ["/contacts/customers/"], """
The customer page shows everything about one customer.

- **On the left**, a list of all customers with their balances. Search or sort it and click to move between customers.
- **At the top**: contact details, billing and shipping addresses, notes, and the **Financial summary** (open balance and overdue amount). Click either amount to see those transactions.
- **New transaction ▾** creates an invoice, payment, estimate, sales order, credit note, sales receipt, refund, statement, proposal, contract, task, appointment or feedback request for this customer.
- **Edit ▾** edits the customer, prints a statement, or makes the customer inactive.

**Tabs**: Transaction list, Activity feed, Statements, Recurring transactions, Projects, Customer details, Documents & files, Notes, Tasks, Opportunities and Conversations.

The **transaction list** can be filtered by type, status and date (last 12 months by default). Tick rows to print or export them together. Each row has View/Edit, a quick action such as **Receive payment**, and a ▾ menu with Print, Send, Make a copy and Void.
"""),
    ("quotes", "sales", "Estimates (quotations)", ["/sales/quotes/"], """
An estimate (quotation) prices goods or services before the customer orders.

1. Choose **Create → Estimate (quotation)**.
2. Pick the customer. Their email, addresses and terms fill in automatically.
3. Add the lines (see "Entering lines").
4. Save, then print it, share the link or send it by email.

From an accepted estimate you can create a **sales order** or an **invoice** directly, so nothing is typed twice. An estimate can also supply the pricing for a **proposal** in the Customer Hub.
"""),
    ("orders", "sales", "Sales orders", ["/sales/orders/"], """
A sales order records what the customer ordered and what is still to deliver.

- Create it from **Create → Sales order**, or from an estimate.
- When you invoice, TriB tracks the quantities invoiced, and the order shows as part-invoiced until everything is billed.
- Open orders appear in the **Customer orders** widget on the dashboard.
"""),
    ("invoices", "sales", "Invoices", ["/sales/invoices/"], """
1. Choose **Create → Invoice**, or **New transaction → Invoice** on the customer page.
2. **Customer**: the email, Bill to, Ship to and terms fill in from the customer card. Use **Edit customer** to correct the card.
3. **Cc/Bcc** adds more email recipients.
4. **Terms** (Due on receipt, Net 15/30/45/60/90) set the due date. Typing your own due date changes the terms to Custom.
5. Optional: Ship via, shipping date, tracking number, customer PO number, warehouse, currency and branch.
6. **Amounts are**: choose **Inclusive of VAT** when your prices already contain VAT. TriB takes the VAT out of each line, so a rate of 1,140 at 14% becomes 1,000 sales plus 140 VAT.
7. **Tags** label the invoice (for example "Haulage: Same day"). Lists can be filtered by tag.
8. Enter the lines, then use the bar at the bottom right.

**Balance due** is shown at the top right. Stock items leave the chosen warehouse at FIFO cost when the invoice is posted.
"""),
    ("action-bar", "sales", "The action bar: save, post, print and share", [], """
Every document has a bar fixed at the bottom of the screen.

**Left side**
- **Print or download**: Print, Download PDF (choose "Save as PDF" as the printer) and Print delivery note (the document without prices). Drafts print marked DRAFT.
- **Make recurring**: creates the document again on a schedule (see Recurring transactions).
- **More actions**: Make a copy, Delete (drafts only), Void (posted documents), Transaction journal (the ledger entry) and Audit history.

**Right side**
- **Cancel**, and **Save ▾** with Save and new, and Save and close.
- The green button posts the document. Its ▾ also offers **Save and share link**, **Save & share (WhatsApp)** and, for invoices and estimates, **Save and review to send**.

**Share link** creates a private, read-only page your customer can open without signing in, to view, print and save the document. You can switch the link off at any time. **WhatsApp** opens with a ready message and the link, addressed to the customer's mobile.
"""),
    ("send-email", "sales", "Review and send by email", ["/docs/"], """
1. Open a posted invoice or estimate and select **Review and send**.
2. Check the preview, and edit To, Cc, Bcc, subject and message.
3. Select **Send**. The email carries a **View** button that opens the document's private link.

Every email sent is recorded in the audit log.

Note: Sending needs the company mailbox to be set up by your administrator. Until then, use Share link, WhatsApp or print.
"""),
    ("sales-receipts", "sales", "Sales receipts (cash sales)", ["/sales/receipts/"], """
A sales receipt is an invoice paid on the spot. Choose **Create → Sales receipt**, pick where the money goes (a cash box or bank account), and post. TriB posts the sale and the money received in one step.
"""),
    ("payments", "sales", "Receiving payments", ["/sales/payments/"], """
1. Choose **Create → Receive payment**, or **Receive payment** on an open invoice.
2. Pick the customer, the date, the amount and how they paid: cash, bank transfer or cheque.
3. Allocate the payment to the invoices it settles. Anything left over stays on account and can be used later.
4. For a cheque, enter its number, bank and due date. It goes to **Cheques in the safe** (see Cheques).

Print a receipt from the payment page.
"""),
    ("credit-notes", "sales", "Credit notes and refunds", ["/sales/credits/", "/sales/refunds/"], """
- A **credit note** reduces what a customer owes, for example for returned goods or a price correction. Create it from **Create → Credit note** or from an invoice. Returned stock goes back to the warehouse at its original cost. Posting the credit applies it to the original invoice automatically.
- Unused credit can be applied to another invoice, or paid back with a **refund** (Create → Refund receipt).
"""),
    ("statements", "sales", "Statements and balance confirmations", ["/sales/statements/", "/sales/confirmations/"], """
- **Statements** come in two types. **Balance forward** lists every invoice, payment, credit, refund and returned cheque in a period with the running balance. **Open items** lists only what is unpaid, with each invoice's due date and days overdue.
- Every statement ends with the amount due by age: Current, 1–30, 31–60, 61–90, 91–120 and Over 120 days past the due date.
- The **Statement** button on the customer page opens the statement straight away. **Print / save as PDF** prints it on one A4 page; **Email to customer** sends it with the statement itself in the email.
- **Batch statements** does every customer with a balance (or only overdue ones) at once: **Print all**, one per page, or email each customer their own. Customers without an email address are listed so you can print theirs.
- **Balance confirmations** produce letters asking customers to confirm their balance on a date, which is useful for audits.
"""),

    # ---------------- Purchases ----------------
    ("suppliers", "purchases", "Suppliers and the supplier page", ["/contacts/suppliers/"], """
The supplier page works like the customer page: the list of suppliers on the left, contact and **Bill payment info** (bank details) at the top, the financial summary, and **New transaction ▾** with Bill, Expense, Cheque, Purchase order, Supplier credit, Item receipt, Pay bills and Import bills.

The transaction list shows bills, payments, supplier credits, purchase orders and item receipts, with filters and batch printing.
"""),
    ("purchase-orders", "purchases", "Purchase orders and approval", ["/purchases/orders/"], """
1. Choose **Create → Purchase order**, pick the supplier and warehouse, and add the lines.
2. **Submit for approval**. An approver approves it or returns it with a reason.
3. Once approved, the order is **open**. Use **Receive goods** when the goods arrive, and **Create bill** when the invoice comes.

You can print a draft purchase order to check it; it is marked DRAFT until it has a number.
"""),
    ("item-receipts", "purchases", "Item receipts (goods received notes)", ["/purchases/receipts/"], """
An item receipt puts goods into stock when they arrive, before or without the supplier's bill.

- Batch-tracked items need a **batch number** and an **expiry date**, so the warehouse knows what expires when. Goods that have already expired cannot be received.
- Serial-tracked items need their **serial numbers**.
- Received but not yet billed goods are held in "Goods received not invoiced" until the bill arrives.
"""),
    ("bills", "purchases", "Bills", ["/purchases/bills/"], """
1. Choose **Create → Bill**, or create it from a purchase order.
2. Enter the supplier's invoice number. TriB warns you if the same number was already entered for that supplier.
3. Add the lines: products, or expense accounts for services and costs. Choose whether amounts are inclusive of VAT.
4. Post the bill. It appears in **Bills to pay** when due.
"""),
    ("import-bills", "purchases", "Importing bills from Excel", ["/purchases/bills/import/"], """
1. Open **Bills → New transaction → Import bills**.
2. **Download template**. Fill one row per bill line: Supplier (code or name), Supplier invoice no, Date (dd/mm/yyyy), Due date, Product SKU or Account code, Description, Qty, Rate and VAT %.
3. Upload the file. TriB checks every row and lists any problems.
4. Select **Create draft bills**. Check the drafts and post them.

Rows with the same supplier and invoice number become one bill. Stock items are received with an item receipt instead.
"""),
    ("pay-bills", "purchases", "Paying bills and remittance advice", ["/purchases/payments/"], """
1. Choose **Pay bills**, pick the supplier and how you pay: cash, bank transfer or cheque.
2. Tick the bills to settle and the amounts. A cheque goes to **Cheques issued** until it clears.
3. After you save, TriB opens the **remittance advice**: each invoice paid with its amount, credits and earlier payments, what this payment pays and what is still open. **Print** it, or **Email to supplier** (the advice is inside the email).
4. On the supplier page, tick several payments and use **Batch actions → Print selected** or **Email remittance advice** to send them together.
"""),
    ("supplier-credits", "purchases", "Supplier credits", ["/purchases/credits/"], """
A supplier credit records money a supplier owes you back, for example for returned goods. Returned stock leaves the warehouse. Apply the credit to a bill to reduce what you owe.
"""),
    ("expenses", "purchases", "The expenses list and changing categories", ["/purchases/expenses/"], """
**Expenses** shows expenses, cheques, bills, bill payments and supplier credits in one list, with the category, the amount before VAT, the VAT and the total.

- Filter by type and dates, or open **Filter** for status, payee and category.
- **Change a category on the row**: pick the new account from the Category list. For a posted transaction, TriB posts a reclassification entry dated today, moving the amount from the old account to the new one, and records it in the audit log. Lines split across several accounts show "--Split--" and are changed on the document itself.
"""),

    # ---------------- Banking ----------------
    ("bank-accounts", "banking", "Bank accounts and cash boxes", ["/banking/accounts/", "/banking/banks/"], """
Each bank account and cash box has its own ledger account and currency. Balances appear on the dashboard and in **Banking & cheques → Bank accounts**. Foreign-currency accounts show both the currency amount and its value in EGP.
"""),
    ("bank-transactions", "banking", "Bank transactions, rules and reconciliation", ["/banking/transactions/", "/banking/rules/", "/banking/reconcile/"], """
1. **Import** your bank statement (Excel or CSV) and match the columns once.
2. Each line can be **matched** to an existing entry, **added** as a new one, recorded as a **cheque** clearing, or **excluded**.
3. **Rules** categorise repeating lines automatically, for example bank charges.
4. **Reconcile** ticks off the statement against the ledger until the difference is zero.

Cheques in the statement are recognised by their number and cleared automatically.
"""),
    ("cheques", "banking", "Cheques", ["/banking/cheques/"], """
**Received cheques** move through these stages: in the safe → under collection (deposited) → cleared, or **returned** (bounced).
**Issued cheques** stay issued until they clear or are cancelled.

- The tiles at the top filter by status. The dashboard shows cheques due this week.
- Choose an action on each cheque: deposit for collection, cleared, bounced, or cancel.
- Every change is kept in the cheque's history.
"""),
    ("returned-cheques", "banking", "Returned (bounced) cheques", ["/banking/cheques/returned/"], """
When the bank sends a list of returned cheques:

1. Open **Returned cheques** and enter the notice: the cheque numbers and the reason.
2. Check the preview and confirm. The amount goes back onto the customer's account.
3. Later, **resubmit** the cheque to the bank, or **settle** it in cash.
"""),
    ("cheque-reconciliation", "banking", "Cheque reconciliation", ["/banking/cheques/reconciliation/"], """
Cheque reconciliation compares the cheques in TriB with the bank statement: cleared cheques with their numbers and amounts, and outstanding cheques not yet presented or cleared. Clearing updates the payables and receivables ledgers automatically. Export it to Excel for your records.
"""),
    ("deposits-transfers", "banking", "Bank deposits and transfers", ["/banking/deposits/", "/banking/transfers/"], """
- A **bank deposit** pays received cheques and cash into the bank on one deposit slip. Print the slip for the bank.
- A **transfer** moves money between your own accounts. Between currencies, enter the amount that arrived; any difference goes to exchange gain or loss.
"""),

    # ---------------- Accounting ----------------
    ("chart", "accounting", "Chart of accounts", ["/ledger/accounts/"], """
Accounts are grouped under header accounts and have a type: asset, liability, equity, income or expense. Some accounts have a **system role** (cash, bank, customers, VAT, inventory and so on), so TriB knows where to post automatically. Every account opens its statement from the reports.
"""),
    ("vouchers", "accounting", "Vouchers and approval", ["/vouchers/"], """
- **Receipt voucher** (سند قبض): money received that is not a customer payment.
- **Payment voucher** (سند صرف): an expense paid in cash, by bank or by cheque.
- **Journal voucher** (قيد يومية): any adjustment with debits and credits that must balance.

1. Create the voucher, then **Save and submit for approval**.
2. The approver sees it in the business feed and Approvals, then approves it or rejects it with a reason.
3. Approved vouchers are posted, automatically if your settings say so.

The person who creates a voucher cannot approve it, and each role has a maximum amount it may approve.
"""),
    ("journals", "accounting", "Journal entries", ["/ledger/journals/"], """
Every posted document creates a journal entry. Open any entry to see its lines, its source document and who posted it. To correct a posted entry, **reverse** it; nothing is ever deleted.
"""),
    ("recurring", "accounting", "Recurring transactions", ["/recurring/"], """
1. Open a posted invoice, bill or voucher and select **Make recurring**, or go to **Recurring transactions**.
2. Choose how often (weekly, monthly, quarterly, yearly), the next date and an end date.
3. When a date comes, TriB tells you in the business feed. Select **Create** to make the drafts, then check and post them.
"""),
    ("projects-costcentres", "accounting", "Cost centres and projects", ["/ledger/cost-centres/", "/projects/"], """
Tag lines with a **cost centre** or **project** to see profit and costs by department or job. **Project profitability** shows income, costs and profit per project.
"""),
    ("vat", "accounting", "VAT rates and the VAT return", ["/ledger/vat-rates/", "/reports/vat-return/"], """
VAT rates (standard 14%, zero-rated, exempt, out of scope) are set under **VAT rates**. The **VAT return** report lists output and input VAT by rate for the month and checks it against the ledger, ready for filing.
"""),

    # ---------------- Inventory ----------------
    ("products", "inventory", "Products and services", ["/inventory/items/", "/inventory/categories/", "/inventory/price-rules/"], """
Each product has a SKU, a barcode, English and Arabic names, a category, a picture, sales and purchase descriptions, sales and purchase prices, VAT rates and a reorder level. Choose its tracking: none, **batch and expiry** (consumables), or **serial numbers** (machines). Services and non-stock items are not counted.

- **New product/service ▾** starts a stock item, a non-stock item or a service.
- The banner lists stock items with no initial cost, out of stock, or at or below their reorder level; **Add now** and **See all** open them.
- Search, **Type**, **Stock status** (in stock, low, out) and **Filters** (category, active or inactive, tracking) narrow the list. Click a column heading to sort.
- The **pencil** turns on edit mode: change prices, costs, reorder levels and categories in the list, then **Save all**. **Customise** (the gear) chooses the columns.
- Each row's **Edit ▾** offers Run report (every sale and purchase of the product), Duplicate, Make inactive, Starting value, Adjust quantity and Print label.
- Tick several rows for **batch actions**: make inactive or active, assign a category, adjust quantity, print labels.
- **More ▾** has categories, **Price rules**, reports, **Starting value**, barcode labels and **Import products** from Excel.

Tip: **Price rules** raise or lower prices for chosen customers, categories or products between two dates. They are applied when a product is added to an invoice, quote or sales order, and you can still change the price on the line.
"""),
    ("stock", "inventory", "Stock, FIFO cost and warehouses", ["/inventory/", "/inventory/stock/", "/inventory/warehouses/"], """
Stock is kept per warehouse and valued at **FIFO** (first in, first out) cost. Every receipt creates a cost layer, and sales use the oldest layers first. **Inventory** shows quantity and value per warehouse. The **Inventory valuation detail** report lists every layer.
"""),
    ("expiry", "inventory", "Batches and expiry", ["/inventory/expiry/"], """
Batch items carry their batch number and expiry date from the moment they are received. **Batches & expiry** lists stock by expiry date. Expired batches cannot be sold. The dashboard warns you about batches expiring within 60 days and about expired stock.
"""),
    ("stock-docs", "inventory", "Transfers, adjustments and stock take", ["/inventory/transfers/", "/inventory/adjustments/", "/inventory/counts/"], """
- A **transfer** moves stock between warehouses at its FIFO cost, keeping batches, expiry dates and serial numbers.
- An **adjustment** adds stock (enter the cost, batch and expiry) or removes it (taken at FIFO cost), with a reason such as damaged, expired or lost.
- A **stock take** compares counted quantities with the system. Scan barcodes to count, then post the differences as an adjustment.
- **Barcode labels** prints labels for products.
"""),

    # ---------------- Assets ----------------
    ("assets", "assets", "Fixed assets and depreciation", ["/assets/"], """
- The **asset register** holds each asset's cost, residual value, useful life, location and custodian.
- **Depreciation** previews the monthly charge for every asset, then posts it in one journal.
- **Dispose** of an asset to record its sale or write-off; the gain or loss is posted automatically.
- **Asset count** checks assets on site by scanning their barcode labels.
"""),

    # ---------------- Payroll ----------------
    ("team", "payroll", "Team: employees, attendance and leave", ["/team/"], """
Employees hold their personal, job and pay details. You can import them from a payroll sheet (check the preview first). Record **attendance**, **leave**, **medical plans** and **loans and advances**; loan instalments are deducted in payroll automatically.
"""),
    ("payroll", "payroll", "Payroll runs", ["/payroll/"], """
1. Create the month's **payroll run**. TriB calculates gross pay, social insurance, salary tax, loans and other deductions.
2. **Prepare** the run, then the Finance manager **approves** it and, above the limit, the Managing director **authorises** it.
3. **Pay** it from the bank. The salary journal and payment are posted.
4. Print **payslips**, and export the **deductions workbook** (deductions, social insurance, salary tax, payments, GL journal).

**Leave provision** values the leave owed to employees.
"""),

    # ---------------- CRM ----------------
    ("crm-overview", "crm", "Customer Hub overview", ["/crm/"], """
The **Customer Hub** brings sales follow-up together: the open pipeline value (and its weighted value), new leads this month, win rate, upcoming appointments, tasks due and deals expected to close. Use **New ▾** to add a lead, opportunity, proposal, contract, appointment, task or conversation, or to request feedback.
"""),
    ("leads", "crm", "Leads", ["/crm/lead/", "/crm/leads/"], """
A lead is a possible customer. Record the business, contact, phone, email, source (website, referral, exhibition…), status and owner. Log calls, tasks and appointments against it. When they buy, select **Convert to customer**: TriB creates the customer and moves the lead's opportunities, tasks, appointments and conversations across.
"""),
    ("opportunities", "crm", "Opportunities and the pipeline", ["/crm/opportunit"], """
An opportunity is a possible sale, with its value, probability, expected close date and owner.

- The **pipeline board** shows a column for each stage: New, Qualified, Proposal, Negotiation, Won and Lost. **Drag a card** to move it to another stage.
- Link an **estimate** for the pricing, and create a **proposal** from the opportunity.
- Won and lost dates are recorded for the win-rate figures.
"""),
    ("proposals", "crm", "Proposals", ["/crm/proposal"], """
1. Create a proposal for a customer, with a cover letter, scope and deliverables, and terms. Choose an estimate to supply the pricing table.
2. **Share link** sends it, by link or WhatsApp. The customer reads it and selects **Accept** after typing their name.
3. When it is accepted, select **Create sales order**; the opportunity is marked won.
"""),
    ("contracts", "crm", "Contracts", ["/crm/contract"], """
Contracts record the customer, title, start and end dates, value, terms and status (draft, sent, active, expired, cancelled). Attach the signed copy. Share it by link for the customer to accept online. Set **Remind me before the end** so renewals are not missed.
"""),
    ("appointments", "crm", "Appointments", ["/crm/appointment", "/crm/calendar/"], """
Book meetings with customers or leads, with a time, length, location and the people from your team attending. The **week calendar** shows them day by day; select **+** on a day to add one. Today's appointments appear in the business feed.
"""),
    ("tasks", "crm", "Tasks", ["/crm/task"], """
Tasks have a due date and an owner, and can be linked to a customer, supplier, lead or opportunity. Tick the circle to mark one done. **My open tasks** shows yours, and overdue tasks appear in your business feed.
"""),
    ("conversations", "crm", "Conversations", ["/crm/conversation"], """
Log every call, meeting, email or WhatsApp exchange with a customer or lead: when it happened, what was said, and a follow-up date. The log appears on the customer's **Conversations** tab, so anyone can pick up where a colleague left off.
"""),
    ("reviews", "crm", "Reviews and requesting feedback", ["/crm/reviews/"], """
**Request feedback** creates a private link where the customer rates you from 1 to 5 stars and leaves a comment. Send it by WhatsApp or email. Ratings appear under **Reviews**, with your average.
"""),

    # ---------------- Reports ----------------
    ("reports", "reports", "The Reports page", ["/reports/"], """
- Reports are grouped into Business overview, Who owes you, Sales and customers, What you owe, Expenses and suppliers, VAT, Employees and payroll, Inventory, Fixed assets, Banking and cheques, and For my accountant.
- Search with **Type report name here**.
- Star ★ a report to keep it in **Favourites**.
- The ⋮ menu opens, exports to Excel or prints a report.

On each report, pick the **Report period** (This month, Last quarter, Last 12 months…) or your own dates, then **Run report**. **Export to Excel** and **Print** are at the top. Rows open the detail behind them.

Tip: Set the period every report opens with under **Default report settings**.
"""),
    ("key-reports", "reports", "Key reports explained", ["/reports/profit", "/reports/balance", "/reports/cash-flows/"], """
- **Profit and loss** (plus comparison, by month, by customer and detail): income less expenses.
- **Balance sheet** (and comparison): what the company owns and owes on a date.
- **Statement of cash flows**: where cash came from and went (operating, investing, financing). It always reconciles to your cash and bank balances.
- **AR / AP ageing** and **customer / supplier balances**: who owes what, and how late.
- **Trial balance**, **General ledger**, **Journal** and **Account list** are for your accountant.
"""),
    ("cash-planning", "reports", "Cash flow overview and forecast", ["/reports/cash-flow"], """
- **Cash flow overview**: cash at each month end for the last 12 months, with money in and out. Select a month for its statement of cash flows.
- **Cash flow forecast**: the next 8 weeks, from today's cash plus cheques due in, invoices due, cheques you issued, bills due and payroll at each month end. Overdue customer invoices are not counted, because when they will be paid is unknown.

Set a **minimum cash balance** in Settings → Account and settings. The business feed warns you when the forecast falls below it.
"""),

    # ---------------- Working faster ----------------
    ("lines", "faster", "Entering lines quickly", [], """
- Type in the **product** box to search by SKU, barcode, or English or Arabic name. The price, VAT and description fill in.
- **Tab** moves along the line. **Enter** goes to the next line, adding one at the end.
- **⊕** at the start of a line: **Add product or service** inserts a line below; **Add subtotal** adds a subtotal of the lines above it.
- Drag **⠿** to put lines in a different order.
- The bin icon, or **Ctrl+Delete**, removes a line.
- **Columns** shows or hides columns. Drag a column edge to resize it; TriB remembers your widths on this computer.
"""),
    ("lists", "faster", "Filtering, printing and exporting lists", [], """
- **Filter** opens the panel: status, delivery method, date (a preset or your own dates), customer or supplier, category and project. **Apply** to filter, **Reset** to clear.
- The filters in use appear as chips; select **×** on a chip to remove that one.
- The icons at the top right print the list, export it to Excel, and choose which columns to show.
"""),
    ("shortcuts", "faster", "Keyboard shortcuts", [], """
- **/** jumps to the search box.
- **Tab** moves to the next field or cell.
- **Enter**, in a line grid, goes to the next line or adds one.
- **Ctrl+Delete**, in a line grid, removes the line.
- **↓ / ↑**, in a product or account picker, move through the list.
- **Esc** closes a menu or picker.
"""),
    ("bookmarks-alerts", "faster", "Bookmarks and alerts", ["/bookmarks/", "/alerts/"], """
- Select the **star** at the top of any page, or the bookmark icon beside any menu item, to add it to **Bookmarks**. Use **Edit bookmarks** to rename or reorder them.
- The **bell** shows your alerts: the same items as the business feed. Select one to open the list behind it.
"""),

    # ---------------- Data ----------------
    ("attachments", "data", "Attachments and receipts", ["/attachments/", "/receipts/"], """
Attach PDFs, photos, Excel or Word files (up to 10 MB each) to any document, customer, supplier or contract. **Attachments** in Settings lists every file. **Upload receipts** collects receipts first; record the expense, then attach the receipt to it.
"""),
    ("audit", "data", "Audit log", ["/audit/"], """
The audit log records every important action: who did it, when, and from where. **Audit history** on a document shows only that document's records.
"""),
    ("privacy", "data", "Privacy, cookies, feedback and subscription", ["/privacy/", "/cookies/", "/feedback/"], """
- **Privacy**: how your data is handled, and the option to hide amounts on the dashboard when you open it.
- **Cookies**: TriB uses only the cookies it needs. "Clear what this computer remembers" resets column widths and similar choices.
- **Feedback**: send ideas or report problems to the TriB team.
- **Subscriptions and billing**: your plan, active users and add-ons.
"""),
]
