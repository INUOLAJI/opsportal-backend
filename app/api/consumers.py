from channels.generic.websocket import AsyncJsonWebsocketConsumer


class DashboardConsumer(AsyncJsonWebsocketConsumer):
    """
    ws://.../ws/dashboard/?token=<access_token>

    Admins join a single shared 'admin_dashboard' group and see every task
    and activity event. Staff join a personal 'staff_<id>_dashboard' group
    and only see events for tasks assigned to them — mirroring the same
    scoping already enforced by TaskListCreateView.get_queryset in views.py.
    """

    async def connect(self):
        user = self.scope.get('user')

        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.user = user
        is_admin = bool(user.role == 'admin' or user.is_superuser)
        company_id = user.company_id or 0
        self.group_name = f'company_{company_id}_admin_dashboard' if is_admin else f'company_{company_id}_staff_{user.id}_dashboard'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # --- group_send handlers -------------------------------------------------
    # channel_layer.group_send({"type": "task.created", ...}) dispatches to
    # task_created below (Channels converts dots to underscores in the type).

    async def task_created(self, event):
        await self.send_json({"type": "task_created", "task": event["task"]})

    async def task_updated(self, event):
        await self.send_json({"type": "task_updated", "task": event["task"]})

    async def activity_created(self, event):
        await self.send_json({"type": "activity_created", "activity": event["activity"]})