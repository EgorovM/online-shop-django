import math
import datetime

import requests

from django.core.mail import send_mail
from django.utils import timezone
from django.core import serializers
from django.conf import settings
from django.db import models


from analysis.models import AnalysInBranch, Analys, LabaratoryBranchShop, SamplingType
from shop.cart import Cart


class PromoCode(models.Model):
    #TODO: max_length?
    text = models.CharField(max_length=32)

    discount = models.FloatField(default=0)
    start_date = models.DateTimeField()
    expiration_date = models.DateTimeField(blank=True, null=True)

    is_infinity = models.BooleanField(default=False)
    use_count = models.IntegerField(default=0)

    def get_promocode(text):
        promocode = PromoCode.objects.filter(text=text).first()

        if (not promocode is None) and (promocode.use_count > 0 or promocode.is_infinity):
            if not promocode is None and promocode.start_date <= timezone.now():
                if promocode.expiration_date is None or timezone.now() <= promocode.expiration_date:
                    return promocode

    def use(self, price):
        koef = self.discount / 100
        price -= price * koef

        return math.ceil(price)

    def __str__(self):
        return self.text


class OrderAnalys(models.Model):
    order = models.ForeignKey('Order', on_delete=models.CASCADE)
    analys = models.ForeignKey(Analys, on_delete=models.CASCADE)
    price = models.FloatField()
    real_price = models.FloatField()
    quantity = models.IntegerField()

    def get_information(self):
        return {
            "Name": self.analys.name[:128],
            "Price": int(self.price * 100),
            "Quantity": self.quantity,
            "Amount": int(self.price * self.quantity * 100),
            "ShopCode": self.analys.id,
            "Tax": "none",
        }


class OrderSampling(models.Model):
    order = models.ForeignKey('Order', on_delete=models.CASCADE)
    sampling = models.ForeignKey(SamplingType, on_delete=models.CASCADE)
    price = models.FloatField()

    def get_information(self):
        return {
            "Name": self.analys.name[:128],
            "Price": int(self.price * 100),
            "Quantity": 1,
            "Amount": int(self.price * self.quantity * 100),
            "Tax": "none",
        }


class Order(models.Model):
    labaratory_shop = models.ForeignKey(LabaratoryBranchShop, on_delete=models.CASCADE)

    name = models.CharField(max_length=127)
    telephone = models.CharField(max_length=32)
    email = models.EmailField()
    birthday = models.CharField(max_length=32)
    price = models.FloatField()

    promocode = models.ForeignKey('PromoCode', on_delete=models.CASCADE, blank=True, null=True)

    make_date = models.DateTimeField(auto_now=True)
    is_verified = models.BooleanField(default=False)

    payment_id = models.CharField(max_length=16, blank=True)

    def __str__(self):
        return f"order #{self.id} {self.is_verified}"

    def make_order(request):
        try:
            order = Order()
            cart = Cart(request)

            order.name = request.POST.get('valid-name')
            order.birthday = datetime.datetime.strptime(request.POST.get('valid-birthday'), "%d-%m-%Y").date()
            order.telephone = request.POST.get('valid-telephone')
            order.email = request.POST.get('valid-email')
            order.price = cart.total_price
            order.labaratory_shop = LabaratoryBranchShop.objects.get(id=request.POST.get('lab_shop_id'))
            order.save()

            promocode_text = request.POST.get('valid-promocode', '')
            promocode = PromoCode.get_promocode(text=promocode_text)

            if not promocode is None:
                order.promocode = promocode
                promocode.use_count -= 1
                promocode.save()

            analysis_price = 0

            for _, product in cart.cart.items():
                analys = Analys.objects.get(id=product['analys_id'])

                price = product['price']
                if not promocode is None:
                    price = promocode.use(float(product['price']))

                analysis_price += float(price)

                product['quantity'] = 1 #remove for quantity

                OrderAnalys.objects.create(
                    order=order,
                    analys=analys,
                    price=price,
                    real_price=product['price'],
                    quantity=product['quantity']
                )

            for sm in cart.get_samplings():
                OrderSampling.objects.create(
                    order=order,
                    sampling=sm.sampling_type,
                    price=sm.price
                )

            order.price = analysis_price + cart.sampling_price
            order.save()

            return order

        except Exception as e:
            print(e)
            return None

    def get_items(self, with_code=False):
        items = []
        total = 0

        for order_item in self.orderanalys_set.all():
            info = order_item.get_information()
            if with_code: info['Code'] = order_item.analys.code
            total += info['Amount']
            items.append(info)

        if total != self.price * 100:
            items.append({
                "Code": "-1",
                "Name": "???????????? ??????????????????????????",
                "Price": self.price * 100 - total,
                "Quantity": 1,
                "Amount": int(self.price * 100 - total),
                "Tax": "none",
            })

        return items

    def to_lab_html(self):
        answer = ""

        if self.labaratory_shop.labaratory.labaratory.id == 3:
            answer = f"""
???????????? ????????!

???????????????????? ???????????????? ?? ?????? ????????.
?????????? ??????????: {self.labaratory_shop.address}
??????: {self.name}
???????? ????????????????: {self.birthday}
            """

            for item in self.orderanalys_set.all():
                answer += f"""
??????: {item.analys.code}
????????????????: {item.analys.name[:128]}
????????????????????????: {", ".join([s.name for s in item.analys.sampling_type.all()])}
                """

        return answer + "\n ??????????????"

    def get_html(self, status='??????????????'):
        def details_html():
            html = """
??????????????:
            """

            for item in self.orderanalys_set.all():
                html += f"""
??????: {item.analys.code}
????????????????: {item.analys.name[:128]}
??????????????????: {item.real_price} ??????.
                """

            html += """
C????????:
            """
            for item in self.ordersampling_set.all():
                html += f"""
????????????????: {item.sampling.site_name[:128]}
??????????????????: {item.price} ??????.
                """

            return html

        def promocode_details():
            if self.promocode is None:
                return ""
            else:
                return f"""
????????????????: {self.promocode.text}
????????????: {self.promocode.discount} %.
                """

        return f"""
?????????? #{self.id} {status}.
????????????????: {self.name}
??????????????: {self.telephone}
??????????: {self.email}
???????? ????????????????: {self.birthday}
??????????????????: {self.price} ??????.
??????????????: {self.labaratory_shop.labaratory.name} {self.labaratory_shop.address}
{details_html()}
{promocode_details()}
        """

    def tinkoff_request(self):
        body = {
            "TerminalKey": settings.TINKOFF_TERMINAL_KEY,
            "Amount": int(self.price * 100),
            "OrderId": self.id,
            "Description": "???????????? ???????????? lotoslab.ru",
            "DATA": {
                "Phone": self.telephone,
                "Email": self.email,
            },
            "Receipt": {
                "Email": self.email,
                "Phone": self.telephone,
                "Taxation": "osn",
                "Items": self.get_items()
            }
        }

        headers = {
            'Content-Type': 'application/json',
        }

        result = requests.post(
            'https://securepay.tinkoff.ru/v2/Init',
            headers=headers,
            json=body).json()

        if result["ErrorCode"] == "0":

            send_mail(
                'lotoslab.ru ??????????',
                f'{self.get_html(status="?????? ???? ??????????????")}',
                settings.EMAIL_HOST_USER,
                ['egorov_michil@mail.ru', self.email] + settings.SEND_TO_EMAILS
            )

            self.payment_id = result["PaymentId"]
            self.save()

            return result["PaymentURL"]
