from core.forms_util import CompanyModelForm

from .models import Customer, Supplier

COMMON = ["code", "name_en", "name_ar", "contact_person", "email", "phone", "tax_id", "commercial_register",
          "address", "city", "country", "shipping_address", "currency", "payment_terms_days", "notes", "is_active"]


class CustomerForm(CompanyModelForm):
    class Meta:
        model = Customer
        fields = COMMON[:13] + ["credit_limit"] + COMMON[13:]


class SupplierForm(CompanyModelForm):
    class Meta:
        model = Supplier
        fields = COMMON[:13] + ["bank_details"] + COMMON[13:]
