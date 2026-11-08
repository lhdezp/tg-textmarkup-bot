from aiogram.filters.callback_data import CallbackData


class EditorCB(CallbackData, prefix="ed"):
    action: str
    idx: int = -1
    arg: str = ""


class TemplateCB(CallbackData, prefix="tpl"):
    action: str
    idx: int = -1
