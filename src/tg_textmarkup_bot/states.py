from aiogram.fsm.state import State, StatesGroup


class Compose(StatesGroup):
    editing = State()  # draft exists, preview shown, awaiting callbacks
    syntax_text = State()  # waiting for a message written with light syntax
    segment_text = State()  # waiting for plain text of a new segment
    segment_edit_text = State()  # waiting for replacement text of an existing segment
    segment_formats = State()  # editing formats of segment stored in data["seg_idx"]
    link_url = State()  # waiting for a URL for segment stored in data["seg_idx"]
    photo = State()  # waiting for a photo or photo URL
    inline_buttons = State()  # waiting for "Text | url" rows
    template_name = State()  # waiting for a template name


class TemplateUse(StatesGroup):
    placeholder_value = State()  # waiting for a value of data["tpl_pending"][0]
