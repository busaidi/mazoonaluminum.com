from django.db import models
from .dispatcher import dispatch


class DomainModel(models.Model):
    """
    Base دوميني بسيط:
    - يعطيك self.emit(event) بدل ما تستورد dispatcher كل مرة.
    """

    class Meta:
        abstract = True

    def emit(self, event) -> None:
        dispatch(event)


class StatefulDomainModel(DomainModel):
    """
    Base جاهز لإدارة حقل حالة (state) في أي موديل:
    - فيه change_state(old -> new)
    - يستدعي hook on_state_changed
    """

    class Meta:
        abstract = True

    state_field_name: str = "state"

    def _get_state(self):
        return getattr(self, self.state_field_name)

    def _set_state(self, value):
        setattr(self, self.state_field_name, value)

    def change_state(self, new_state, *, emit_events: bool = True, save: bool = True):
        """
        يغيّر الـ state بشكل مركزي:
        - يمنع إعادة التغيير لنفس القيمة
        - يحفظ التغيير إذا save=True
        - يستدعي on_state_changed(old, new) إذا emit_events=True
        """
        old_state = self._get_state()

        # لا شيء تغيّر
        if old_state == new_state:
            return

        self._set_state(new_state)

        if save:
            self.save(update_fields=[self.state_field_name])

        if emit_events:
            self.on_state_changed(old_state, new_state)

    def on_state_changed(self, old_state, new_state):
        """
        hook فاضي، الموديل الابن (مثل Invoice) يقدر يكتب منطق هنا.
        """
        pass
