import grpc
from order_service.proto import order_pb2, order_pb2_grpc
from loguru import logger
from order_service.model.model import *
from google.protobuf import empty_pb2
from common.register import consul
from order_service.settings import settings
from order_service.proto import goods_pb2, goods_pb2_grpc


class OrderService(order_pb2_grpc.OrderServicer):

    @logger.catch
    def CartItemList(self, request: order_pb2.UserInfo, context):
        items = ShoppingCart.select().where(ShoppingCart.user == request.id)
        rsp = order_pb2.CartItemListResponse()
        rsp.total = items.count()
        for item in items:
            item_rsp = order_pb2.ShopCartInfoResponse()
            item_rsp.id = item.id
            item_rsp.userId = item.user
            item_rsp.goodsId = item.goodsId
            item_rsp.nums = item.nums
            items.checked = item.checked
            rsp.data.append(item_rsp)
        return rsp

    def CreateCartItem(self, request: order_pb2.CartItemRequest, context):
        existed_items = ShoppingCart.select().where(ShoppingCart.user == request.userId,
                                                    ShoppingCart.goods == request.goodsId)
        if existed_items:
            item = existed_items[0]
            item.nums += request.nums
        else:
            item = ShoppingCart()
            item.user = request.userId
            item.goods = request.goodsId
            item.nums = request.nums
        item.save()
        return order_pb2.ShopCartInfoResponse(id=item.id)

    def UpdateCartItem(self, request, context):
        try:
            item = ShoppingCart.get(ShoppingCart.user == request.userId, ShoppingCart.goods == request.goodsId)
            item.checked = request.checked
            if request.nums:
                item.nums = request.nums
            item.save()
            return empty_pb2()
        except DoesNotExist:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Shopping cart does not exist")
            return empty_pb2()

    def DeleteCartItem(self, request, context):
        try:
            item = ShoppingCart.get(ShoppingCart.user == request.userId, ShoppingCart.goods == request.goodsId)
            item.delete_instance()
            return empty_pb2.Empty()
        except DoesNotExist as e:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Shopping cart does not exist")
            return empty_pb2.Empty()

    def convert_order_into_response(self, order: OrderInfo) -> order_pb2.OrderInfoResponse:
        order_rsp = order_pb2.OrderInfoResponse()
        order_rsp.id = order.id
        order_rsp.userId = order.user
        order_rsp.orderSn = order.order_sn
        order_rsp.payType = order.pay_type
        order_rsp.status = order.status
        order_rsp.post = order.post
        order_rsp.total = order.order_amount
        order_rsp.address = order.address
        order_rsp.name = order.signer_name
        order_rsp.mobile = order.singer_mobile
        order_rsp.addTime = order.add_time.strftime('%Y-%m-%d %H:%M:%S')
        return order_rsp

    @logger.catch
    def OrderList(self, request, context):
        rsp = order_pb2.OrderListResponse()
        orders = OrderInfo.select()
        if request.userId:
            orders = orders.where(OrderInfo.user == request.userId)
        rsp.total = orders.count()
        per_page_nums = request.pagePerNums if request.pagePerNums else 10
        start = per_page_nums * (request.pages - 1) if request.pages else 0
        orders = orders.limit(per_page_nums).offset(start)
        for order in orders:
            order_rsp = self.convert_order_into_response(order)
            rsp.data.append(order_rsp)
        return rsp

    def OrderDetail(self, request: order_pb2.OrderRequest, context):
        rsp = order_pb2.OrderInfoDetailResponse()
        try:
            if request.userId:
                order: OrderInfo = OrderInfo.get(OrderInfo.id == request.id, OrderInfo.user == request.userId)
            else:
                order: OrderInfo = OrderInfo.get(OrderInfo.id == request.id)
            rsp.orderInfo = self.convert_order_into_response(order)
            order_goods = OrderGoods.select().where(OrderGoods.order == order.id)
            for order_good in order_goods:
                order_goods_rsp = order_pb2.OrderItemResponse()
                order_goods_rsp.id = order_good.id
                order_goods_rsp.goodsId = order_good.goods
                order_goods_rsp.goodsName = order_good.goods_name
                order_goods_rsp.goodsImage = order_good.goods_image
                order_goods_rsp.goodsPrice = float(order_good.goods_price)
                order_goods_rsp.nums = order_good.nums

                rsp.data.append(order_goods_rsp)

            return rsp
        except DoesNotExist:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Order does not exist")
            return rsp

    def UpdateOrderStatus(self, request, context):
        OrderInfo.update(status=request.status).where(OrderInfo.order_sn == request.orderSn)
        return empty_pb2.Empty()

    def CreateOrder(self, request, context):
        goods_ids = []
        goods_nums = {}
        order_amount = 0
        order_goods_list = []
        for cart_item in ShoppingCart.select().where(ShoppingCart.user == request.userId, ShoppingCart.checked == True):
            goods_ids.append(cart_item.goods)
            goods_nums[cart_item.goods] = cart_item.nums
        if not goods_ids:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("No item in shopping cart")
            return order_pb2.OrderInfoResponse()

        # query goods info from goods srv
        register = consul.ConsulRegister(settings.CONSUL_HOST, settings.CONSUL_POST)
        goods_srv_host, goods_srv_port = register.get_host_port(f'Service == "{settings.Goods_srv_name}"')
        if not goods_srv_host or not goods_srv_port:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Goods service not available")
            return order_pb2.OrderInfoResponse()
        goods_channel = grpc.insecure_channel(f"{goods_srv_host}:{goods_srv_port}")
        goods_stub = goods_pb2_grpc.GoodsStub(goods_channel)
        goods_rsp = goods_stub.BatchGetGoods(goods_pb2.BatchGoodsIdInfo(id=goods_ids))
        for good in goods_rsp.data:
            order_amount += good.shopPrice * goods_nums[good.id]
            order_goods = OrderGoods(goods=good.id, goods_name=good.name, goods_image=good.goodsFrontImage,
                                     goods_price=good.shopPrice, nums=goods_nums[good.id])
            order_goods_list.append(order_goods)


        return super().CreateOrder(request, context)
