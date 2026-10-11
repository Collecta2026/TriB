from core.forms_util import CompanyModelForm

from .models import Customer, Supplier

COMMON = ["code", "name_en", "name_ar", "contact_person", "email", "phone", "tax_id", "commercial_register",
          "address", "city", "country", "shipping_address", "currency", "payment_terms_days", "notes", "is_active"]


class CustomerForm(CompanyModelForm):
    class Meta:
        model = Customer
        fields = COMMON[:13] + ["credit_limit", "account_manager"] + COMMON[13:]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core import access
        from users.models import User

        self.fields["account_manager"].queryset = User.objects.filter(
            memberships__company=self.company, memberships__is_active=True).distinct()
        if access.own_only(access.current()):
            # Salespeople limited to their own records keep the customers they add.
            self.fields.pop("account_manager")


class SupplierForm(CompanyModelForm):
    class Meta:
        model = Supplier
        fields = COMMON[:13] + ["bank_details"] + COMMON[13:]
