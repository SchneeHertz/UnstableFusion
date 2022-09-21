from PyQt5.QtWidgets import *
from PyQt5.QtGui import *
from PyQt5.QtCore import *
import sys
import numpy as np
from PIL import Image
import torch
from torch import autocast
from diffusers import StableDiffusionPipeline, StableDiffusionInpaintPipeline, StableDiffusionImg2ImgPipeline
import cv2
import pathlib
import time
SIZE_INCREASE_INCREMENT = 20

def cv2_telea(img, mask):
    ret = cv2.inpaint(img, 255 - mask, 5, cv2.INPAINT_TELEA)
    return ret, mask


def cv2_ns(img, mask):
    ret = cv2.inpaint(img, 255 - mask, 5, cv2.INPAINT_NS)
    return ret, mask

def get_quicksave_path():
    parent_path = pathlib.Path(__file__).parents[0]
    folder_path = parent_path / 'quicksaves'
    folder_path.mkdir(exist_ok=True, parents=True)
    return folder_path

def get_unique_filename():
    return str(int(time.time())) + ".png"

def quicksave_image(np_image, file_path=None):
    if file_path == None:
        file_path = get_quicksave_path() / (get_unique_filename())

    Image.fromarray(np_image).save(file_path)
    return file_path

def gaussian_noise(img, mask):
    noise = np.random.randn(mask.shape[0], mask.shape[1], 3)
    noise = (noise + 1) / 2 * 255
    noise = noise.astype(np.uint8)
    nmask = mask.copy()
    nmask[mask > 0] = 1
    img = nmask[:, :, np.newaxis] * img + (1 - nmask[:, :, np.newaxis]) * noise
    return img, mask

inpaint_options = ['cv2_ns',
         'cv2_telea',
         'gaussian']
        
inpaint_functions = {
    'cv2_ns': cv2_ns,
    'cv2_telea': cv2_telea,
    'gaussian': gaussian_noise
}

def get_texture():
    SIZE = 512
    Z = np.zeros((SIZE, SIZE), dtype=np.uint8)
    return np.stack([Z, Z, Z, Z], axis=2)


testtexture = get_texture()

def qimage_from_array(arr):
    maximum = arr.max()
    if maximum > 0 and maximum <= 1:
        return  QImage((arr.astype('uint8') * 255).data, arr.shape[1], arr.shape[0], QImage.Format_RGBA8888)
    else:
        return  QImage(arr.astype('uint8').data, arr.shape[1], arr.shape[0], QImage.Format_RGBA8888)

testimage = qimage_from_array(testtexture)

class DummyStableDiffusionHandler:

    def __init__(self):
        pass

    def inpaint(self, prompt, image, mask, strength=0.75, steps=50, guidance_scale=7.5):
        inpainted_image = np.zeros_like(image)
        for i in range(inpainted_image.shape[1]):
            for j in range(inpainted_image.shape[0]):
                inpainted_image[i, j, 0] = 255 * i // inpainted_image.shape[1]
                inpainted_image[i, j, 1] = 255 * j // inpainted_image.shape[1]

        new_image = image.copy()[:, :, :3]
        # new_image[mask > 0] = np.array([255, 0, 0])
        new_image[mask > 0] = inpainted_image[mask > 0]
        return Image.fromarray(new_image)

    def generate(self, prompt, width=512, height=512, strength=0.75, steps=50, guidance_scale=7.5):

        np_im = np.zeros((height, width, 3), dtype=np.uint8)
        np_im[:, :, 2] = 255
        for i in range(np_im.shape[0]):
            np_im[i, :, 1] = int((i / np_im.shape[0]) * 255)
        for j in range(np_im.shape[1]):
            np_im[:, j, 2] = int((j / np_im.shape[0]) * 255)
        return Image.fromarray(np_im)

def dummy_safety_checker(self):
        def check(images, *args, **kwargs):
            return images, [False] * len(images)

        return check
class StableDiffusionHandler:

    def __init__(self):
        self.text2img = StableDiffusionPipeline.from_pretrained(
            "CompVis/stable-diffusion-v1-4",
             revision="fp16",
             torch_dtype=torch.float16,
             use_auth_token=True).to("cuda")

        # self.text2img.safety_checker = dummy_safety_checker

        self.inpainter = StableDiffusionInpaintPipeline(
            vae=self.text2img.vae,
            text_encoder=self.text2img.text_encoder,
            tokenizer=self.text2img.tokenizer,
            unet=self.text2img.unet,
            scheduler=self.text2img.scheduler,
            safety_checker=self.text2img.safety_checker,
            feature_extractor=self.text2img.feature_extractor
        ).to("cuda")

        self.img2img = StableDiffusionImg2ImgPipeline(
            unet=self.text2img.unet,
            scheduler=self.text2img.scheduler,
            vae=self.text2img.vae,
            text_encoder=self.text2img.text_encoder,
            tokenizer=self.text2img.tokenizer,
            safety_checker=self.text2img.safety_checker,
            feature_extractor=self.text2img.feature_extractor
        ).to("cuda")
    
    def inpaint(self, prompt, image, mask, strength=0.75, steps=50, guidance_scale=7.5):
        image_ = Image.fromarray(image.astype(np.uint8)).resize((512, 512), resample=Image.LANCZOS)
        mask_ = Image.fromarray(mask.astype(np.uint8)).resize((512, 512), resample=Image.LANCZOS)

        with autocast("cuda"):
            im = self.inpainter(
                prompt=prompt,
                init_image=image_,
                mask_image=mask_,
                strength=strength,
                num_inference_steps=steps,
                guidance_scale=guidance_scale
            )["sample"][0]
            return im.resize((image.shape[1], image.shape[0]), resample=Image.LANCZOS)
    
    def generate(self, prompt, width=512, height=512, strength=0.75, steps=50, guidance_scale=7.5):
        with autocast("cuda"):
            im = self.text2img(
                prompt=prompt,
                width=512,
                height=512
            )["sample"][0]

            return im.resize((width, height), resample=Image.LANCZOS)
    
    def reimagine(self, prompt, image, steps=50, guidance_scale=7.5):

        image_ = Image.fromarray(image.astype(np.uint8)).resize((512, 512), resample=Image.LANCZOS)
        with autocast("cuda"):
            results = self.img2img(
                [prompt],
                init_image=image_,
                num_inference_steps=steps,
                guidance_scale=guidance_scale
            )["sample"]
            print(len(results))
            im = results[0]
            return im.resize((image.shape[1], image.shape[0]), resample=Image.LANCZOS)

class PaintWidget(QWidget):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.np_image = None
        self.qt_image = None
        self.selection_rectangle = None
        self.selection_rectangle_size = (100, 100)
        self.is_dragging = False
        self.image_rect = None

        self.strength = 0.75
        self.steps = 50
        self.guidance_scale = 7.5

        self.inpaint_method = inpaint_options[0]

        self.history = []
        self.future = []
        self.color = np.array([0, 0, 0])

        self.setAcceptDrops(True)
        self.scratchpad = None
        self.owner = None
    
    def dragEnterEvent(self, e):
        if e.mimeData().hasImage:
            e.accept()
        else:
            e.ignore()
        
    def dropEvent(self, e):
        imdata = Image.open(e.mimeData().text()[8:])
        image_numpy = np.array(imdata)
        self.set_np_image(image_numpy)
        self.resize_to_image(only_if_smaller=True)
        self.update()
    
    def set_strength(self, new_strength):
        self.strength = new_strength

    def set_steps(self, new_steps):
        self.steps = new_steps

    def set_guidance_scale(self, new_guidance_scale):
        self.guidance_scale = new_guidance_scale
    
    def set_inpaint_method(self, method):
        self.inpaint_method = method
    
    def set_color(self, new_color):
        self.color = np.array([new_color.red(), new_color.green(), new_color.blue()])

    def undo(self):
        if len(self.history) > 0:
            self.future = [self.np_image.copy()] + self.future
            self.set_np_image(self.history[-1], add_to_history=False)
            self.history = self.history[:-1]

    def redo(self):
        if len(self.future) > 0:
            prev_image = self.np_image.copy()
            self.set_np_image(self.future[0], add_to_history=False)
            self.future = self.future[1:]
            self.history.append(prev_image)

    def set_np_image(self, arr, add_to_history=True):
        if arr.shape[-1] == 3:
            arr = np.concatenate([arr, np.ones(arr.shape[:2] + (1,)) * 255], axis=-1)

        if arr.dtype != np.uint8:
            arr = arr.astype(np.uint8)

        if add_to_history == True:
            self.future = []

        if add_to_history and (not (self.np_image is None)):
            self.history.append(self.np_image.copy())

        self.np_image = arr
        self.qt_image = qimage_from_array(self.np_image)

    def mouseMoveEvent(self, e):
        if self.is_dragging:
            self.selection_rectangle.moveCenter(e.pos())

            if e.buttons() & Qt.RightButton:
                self.erase_selection(False)
            if e.buttons() & Qt.MidButton:
                self.paint_selection(False)

            self.update()
            if self.owner != None:
                self.owner.update()

    def mouseReleaseEvent(self, e):
        # if e.button() == Qt.LeftButton:
        self.is_dragging = False

    def update_selection_rectangle(self):
        if self.selection_rectangle != None:
            center = self.selection_rectangle.center()
            self.selection_rectangle = QRect(center.x() - self.selection_rectangle_size[0] / 2, center.y(
            ) - self.selection_rectangle_size[1] / 2, *self.selection_rectangle_size)

    def wheelEvent(self, e):
        delta = 1
        if e.angleDelta().y() < 0:
            delta = -1
        delta *= max(1, self.selection_rectangle_size[0] / 10)

        self.selection_rectangle_size = [self.selection_rectangle_size[0] + delta, self.selection_rectangle_size[1] + delta]

        if self.selection_rectangle_size[0] <= 0:
            self.selection_rectangle_size[0] = 1
        if self.selection_rectangle_size[1] <= 0:
            self.selection_rectangle_size[1] = 1

        if self.selection_rectangle_size[0] > 512:
            self.selection_rectangle_size[0] = 512
        if self.selection_rectangle_size[1] > 512:
            self.selection_rectangle_size[1] = 512

        if self.selection_rectangle != None:
            self.update_selection_rectangle()
        self.update()
        
    def resize_to_image(self, only_if_smaller=False):
        if self.qt_image != None:
            if only_if_smaller:
                if self.qt_image.width() < self.width() and self.qt_image.height() < self.height():
                    return
            self.resize(self.qt_image.width(), self.qt_image.height())

    def map_widget_to_image(self, pos):
        w, h = self.qt_image.width(), self.qt_image.height()
        window_width = self.width()
        window_height = self.height()
        offset_x = (window_width - w) / 2
        offset_y = (window_height - h) / 2
        return QPoint(pos.x() - offset_x, pos.y() - offset_y)
    
    def map_widget_to_image_rect(self, widget_rect):
        image_rect = QRect()
        image_rect.setTopLeft(self.map_widget_to_image(widget_rect.topLeft()))
        image_rect.setBottomRight(self.map_widget_to_image(widget_rect.bottomRight()))
        return image_rect

    def crop_image_rect(self, image_rect):
        source_rect = QRect(0, 0, self.selection_rectangle.width(), self.selection_rectangle.height())

        if image_rect.left() < 0:
            source_rect.setLeft(-image_rect.left())
            image_rect.setLeft(0)
        if image_rect.right() >= self.qt_image.width():
            source_rect.setRight(self.selection_rectangle.width() -image_rect.right() + self.qt_image.width() - 1)
            image_rect.setRight(self.qt_image.width())
        if image_rect.top() < 0:
            source_rect.setTop(-image_rect.top())
            image_rect.setTop(0)
        if image_rect.bottom() >= self.qt_image.height():
            source_rect.setBottom(self.selection_rectangle.height() -image_rect.bottom() + self.qt_image.height() - 1)
            image_rect.setBottom(self.qt_image.height())
        return image_rect, source_rect

    def paint_selection(self, add_to_history=True):
        if self.selection_rectangle != None:
            image_rect = self.map_widget_to_image_rect(self.selection_rectangle)
            image_rect, source_rect = self.crop_image_rect(image_rect)
            new_image = self.np_image.copy()
            new_image[image_rect.top():image_rect.bottom(), image_rect.left():image_rect.right(), :3] = self.color
            new_image[image_rect.top():image_rect.bottom(), image_rect.left():image_rect.right(), 3] = 255
            self.set_np_image(new_image, add_to_history=add_to_history)

    def erase_selection(self, add_to_history=True):
        if self.selection_rectangle != None:
            image_rect = self.map_widget_to_image_rect(self.selection_rectangle)
            image_rect, source_rect = self.crop_image_rect(image_rect)
            new_image = self.np_image.copy()
            new_image[image_rect.top():image_rect.bottom(), image_rect.left():image_rect.right(), :] = 0
            self.set_np_image(new_image, add_to_history=add_to_history)
    
    def set_selection_image(self, patch_image):
        if self.selection_rectangle != None:
            image_rect = self.map_widget_to_image_rect(self.selection_rectangle)
            image_rect, source_rect = self.crop_image_rect(image_rect)
            new_image = self.np_image.copy()
            target_width = image_rect.width()
            target_height = image_rect.height()
            patch_np = np.array(patch_image)[source_rect.top():source_rect.bottom(), source_rect.left():source_rect.right(), :][:target_height, :target_width, :]
            if patch_np.shape[-1] == 4:
                patch_np, patch_alpha = patch_np[:, :, :3], patch_np[:, :, 3]
                patch_alpha = (patch_alpha > 128) * 255
            else:
                patch_alpha = np.ones((patch_np.shape[0], patch_np.shape[1])).astype(np.uint8) * 255

            new_image[image_rect.top():image_rect.top() + patch_np.shape[0], image_rect.left():image_rect.left()+patch_np.shape[1], :][patch_alpha > 128] = \
                np.concatenate(
                    [patch_np, patch_alpha[:, :, None]],
                axis=-1)[patch_alpha > 128]
            self.set_np_image(new_image)


    def get_selection_np_image(self):
        image_rect = self.map_widget_to_image_rect(self.selection_rectangle)
        image_rect, source_rect = self.crop_image_rect(image_rect)
        result = np.zeros((self.selection_rectangle.height(), self.selection_rectangle.width(), 4), dtype=np.uint8)
        result[source_rect.top():source_rect.bottom(), source_rect.left():source_rect.right(), :] = \
            self.np_image[image_rect.top():image_rect.bottom(), image_rect.left():image_rect.right(), :]
        return result

    def increase_image_size(self):
        H = SIZE_INCREASE_INCREMENT // 2
        new_image = np.zeros((self.np_image.shape[0] + SIZE_INCREASE_INCREMENT, self.np_image.shape[1] + SIZE_INCREASE_INCREMENT, 4), dtype=np.uint8)
        new_image[H:-H, H:-H, :] = self.np_image
        self.set_np_image(new_image)

    def decrease_image_size(self):
        H = SIZE_INCREASE_INCREMENT // 2
        self.set_np_image(self.np_image[H:-H, H:-H, :])

    def mousePressEvent(self, e):
        # return super().mousePressEvent(e)
        top_left = QPoint(e.pos().x() - self.selection_rectangle_size[0] / 2, e.pos().y() - self.selection_rectangle_size[1] / 2)
        self.selection_rectangle = QRect(top_left, QSize(*self.selection_rectangle_size))

        if e.button() == Qt.LeftButton:
            self.is_dragging = True

        if e.button() == Qt.RightButton:
            self.erase_selection()
            self.is_dragging = True

        if e.button() == Qt.MidButton:
            self.paint_selection()
            self.is_dragging = True
            # self.selection_rectangle_size = (256, 256)
            # self.update_selection_rectangle()

        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)

        checkerboard_brush = QBrush()
        checkerboard_brush.setColor(QColor('gray'))
        checkerboard_brush.setStyle(Qt.Dense5Pattern)

        if self.qt_image != None:
            w, h = self.qt_image.width(), self.qt_image.height()
            window_width = self.width()
            window_height = self.height()
            offset_x = (window_width - w) / 2
            offset_y = (window_height - h) / 2
            self.image_rect = QRect(offset_x, offset_y, w, h)
            prev_brush = painter.brush()
            painter.fillRect(self.image_rect, checkerboard_brush)
            painter.setBrush(prev_brush)
            painter.drawImage(self.image_rect, self.qt_image)
        if self.selection_rectangle != None:
            # painter.setBrush(redbrush)
            painter.setPen(QPen(Qt.red,  1, Qt.SolidLine))
            painter.drawRect(self.selection_rectangle)
        if self.scratchpad != None and (self.scratchpad.isVisible()):
            if (not (self.scratchpad.np_image is None)) and (not (self.scratchpad.selection_rectangle is None)) and (not (self.selection_rectangle is None)):
                image = np.array(Image.fromarray(self.scratchpad.get_selection_np_image()).resize((self.selection_rectangle.width(), self.selection_rectangle.height()), Image.LANCZOS))
                painter.drawImage(self.selection_rectangle, qimage_from_array(image))



def handle_load_image_button(paint_widget):
    file_name = QFileDialog.getOpenFileName()

    if file_name[0]:
        imdata = Image.open(file_name[0])
        image_numpy = np.array(imdata)
        widget.set_np_image(image_numpy)
        widget.resize_to_image(only_if_smaller=True)
        widget.update()

def handle_erase_button(paint_widget):
    paint_widget.erase_selection()
    widget.update()

def handle_undo_button(paint_widget):
    paint_widget.undo()
    widget.update()

def handle_redo_button(paint_widget):
    paint_widget.redo()
    widget.update()

def handle_generate_button(paint_widget, diffusion_handler, prompt):
    width = paint_widget.selection_rectangle.width()
    height = paint_widget.selection_rectangle.height()
    image = diffusion_handler.generate(prompt, width=width, height=height)
    paint_widget.set_selection_image(image)
    paint_widget.update()

def handle_inpaint_button(paint_widget, diffusion_handler, prompt):
    image_ = paint_widget.get_selection_np_image()
    image = image_[:, :, :3]
    mask = 255 - image_[:, :, 3]

    image, _ = inpaint_functions[paint_widget.inpaint_method](image, 255 - mask)

    inpainted_image = diffusion_handler.inpaint(prompt,
                                                image,
                                                mask,
                                                strength=paint_widget.strength,
                                                steps=paint_widget.steps,
                                                guidance_scale=paint_widget.guidance_scale)

    paint_widget.set_selection_image(inpainted_image)
    paint_widget.update()

def create_select_widget(name, options, select_callback=None):
    container_widget = QWidget()
    selector_widget = QComboBox()
    for option in options:
        selector_widget.addItem(option)
    selector_label = QLabel(name)

    layout = QHBoxLayout()
    layout.addWidget(selector_label)
    layout.addWidget(selector_widget)
    container_widget.setLayout(layout)

    if select_callback != None:
        selector_widget.activated.connect(select_callback)

    return container_widget, selector_widget

def create_slider_widget(name, minimum=0, maximum=1, default=0.5, dtype=float, value_changed_callback=None):
    strength_widget = QWidget()
    strength_slider = QSlider(Qt.Horizontal)
    strength_label = QLabel(name)
    value_text = QLineEdit()
    reset_button = QPushButton('↺')

    def slider_changed():
        value = dtype(strength_slider.value() / 100)
        value_text.setText(str(value))
        if value_changed_callback:
            value_changed_callback(value)

    def value_changed():
        try:
            value = dtype(float(value_text.text()) * 100)
            strength_slider.setValue(value)
            if value_changed_callback:
                value_changed_callback(dtype(value_text.text()))
        except:
            pass

    strength_slider.valueChanged.connect(slider_changed)
    value_text.textChanged.connect(value_changed)

    def reset():
        strength_slider.setValue(default * 100)
        value_text.setText(str(default))

    reset_button.clicked.connect(reset)

    strength_layout = QHBoxLayout()
    strength_layout.addWidget(strength_label)
    strength_layout.addWidget(strength_slider)
    strength_layout.addWidget(value_text)
    strength_layout.addWidget(reset_button)
    strength_widget.setLayout(strength_layout)

    strength_slider.setMinimum(minimum * 100)
    strength_slider.setMaximum(maximum * 100)
    strength_slider.setValue(default * 100)

    strength_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    value_text.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    reset_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    
    strength_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    # set the default value


    return strength_widget, strength_slider, value_text

def handle_quicksave_button(paint_widget):
    quicksave_image(paint_widget.np_image)

def handle_export_button(paint_widget):
    path = QFileDialog.getSaveFileName()
    if path[0]:
        quicksave_image(paint_widget.np_image, file_path=path[0])

def handle_select_color_button(paint_widget, select_color_button):
    color = QColorDialog.getColor()
    if color.isValid():
        paint_widget.set_color(color)


        sheet = ('background-color: %s' % color.name()) + ';' + ('color: %s' % ('black' if color.lightness() > 128 else 'white')) + ';'
        select_color_button.setStyleSheet(sheet)



def handle_paint_button(paint_widget):
    paint_widget.paint_selection()
    paint_widget.update()

def handle_increase_size_button(paint_widget):
    paint_widget.increase_image_size()
    paint_widget.resize_to_image(only_if_smaller=True)
    paint_widget.update()

def handle_decrease_size_button(paint_widget):
    paint_widget.decrease_image_size()
    paint_widget.update()

def handle_show_scratchpad(paint_widget, scratchpad):
    if scratchpad.isVisible():
        scratchpad.hide()
    else:
        scratchpad.show()

def handle_paste_scratchpad(paint_widget, scratchpad):
    if not (scratchpad.np_image is None):
        resized = np.array(Image.fromarray(scratchpad.get_selection_np_image()).resize((paint_widget.selection_rectangle.width(), paint_widget.selection_rectangle.height()), Image.LANCZOS))
        paint_widget.set_selection_image(resized)
        paint_widget.update()

def handle_reimagine_button(paint_widget, diffusion_handler, prompt):

    image_ = paint_widget.get_selection_np_image()
    image = image_[:, :, :3]

    # image, _ = inpaint_functions[paint_widget.inpaint_method](image, 255 - mask)

    # def reimagine(self, prompt, image, steps=50, guidance_scale=7.5):
    reimagined_image = diffusion_handler.reimagine(prompt,
                                                image,
                                                steps=paint_widget.steps,
                                                guidance_scale=paint_widget.guidance_scale)

    paint_widget.set_selection_image(reimagined_image)
    paint_widget.update()

if __name__ == '__main__':
    stable_diffusion_handler = StableDiffusionHandler()
    # stable_diffusion_handler = DummyStableDiffusionHandler()

    app = QApplication(sys.argv)
    tools_widget = QWidget()
    tools_layout = QVBoxLayout()
    load_image_button = QPushButton('Load Image')
    erase_button = QPushButton('Erase')
    paint_widgets_container = QWidget()
    paint_widgets_layout = QHBoxLayout()
    paint_button = QPushButton('Paint')
    select_color_button = QPushButton('Select Color')
    paint_widgets_layout.addWidget(paint_button)
    paint_widgets_layout.addWidget(select_color_button)
    paint_widgets_container.setLayout(paint_widgets_layout)

    increase_size_container = QWidget()
    increase_size_layout = QHBoxLayout()
    increase_size_button = QPushButton('Increase Size')
    decrease_size_button = QPushButton('Decrease Size')
    increase_size_layout.addWidget(increase_size_button)
    increase_size_layout.addWidget(decrease_size_button)
    increase_size_container.setLayout(increase_size_layout)

    undo_redo_container = QWidget()
    undo_redo_layout = QHBoxLayout()
    undo_button = QPushButton('Undo')
    redo_button = QPushButton('Redo')
    undo_redo_layout.addWidget(undo_button)
    undo_redo_layout.addWidget(redo_button)
    undo_redo_container.setLayout(undo_redo_layout)

    reimagine_button = QPushButton('Reimagine')
    inpaint_button = QPushButton('Inpaint')
    prompt_textarea = QLineEdit()
    prompt_textarea.setPlaceholderText('Prompt')
    generate_button = QPushButton('Generate')
    quicksave_button = QPushButton('Quick Save')
    scratchpad_container = QWidget()
    scratchpad_layout = QHBoxLayout()
    show_scratchpad_button = QPushButton('Show Scratchpad')
    paste_scratchpad_button = QPushButton('Paste From Scratchpad')
    scratchpad_layout.addWidget(show_scratchpad_button)
    scratchpad_layout.addWidget(paste_scratchpad_button)
    scratchpad_container.setLayout(scratchpad_layout)
    export_button = QPushButton('Export')
    widget = PaintWidget()
    scratchpad = PaintWidget()
    widget.scratchpad = scratchpad
    scratchpad.owner = widget

    strength_widget, strength_slider, strength_text = create_slider_widget(
        "Strength",
        default=0.75,
        value_changed_callback=lambda val: widget.set_strength(val))

    steps_widget, steps_slider, steps_text = create_slider_widget(
        "Steps",
         minimum=1,
         maximum=200,
         default=50,
         dtype=int,
         value_changed_callback=lambda val: widget.set_steps(val))

    guidance_widget, guidance_slider, guidance_text = create_slider_widget(
        "Guidance",
         minimum=0,
         maximum=10,
         default=7.5,
         value_changed_callback=lambda val: widget.set_guidance_scale(val))
        
    def inpaint_change_callback(num):
        widget.set_inpaint_method(inpaint_options[num])

    inpaint_selector_container, inpaint_selector = create_select_widget(
        'Initializer',
        inpaint_options,
        select_callback=inpaint_change_callback)

    inpaint_container = QWidget()
    inpaint_layout = QHBoxLayout()
    inpaint_layout.addWidget(inpaint_selector_container)
    inpaint_layout.addWidget(inpaint_button)
    inpaint_container.setLayout(inpaint_layout)

    tools_layout.addWidget(load_image_button)
    tools_layout.addWidget(erase_button)
    tools_layout.addWidget(paint_widgets_container)
    tools_layout.addWidget(undo_redo_container)
    tools_layout.addWidget(prompt_textarea)
    tools_layout.addWidget(generate_button)
    # tools_layout.addWidget(inpaint_button)
    tools_layout.addWidget(inpaint_container)
    tools_layout.addWidget(reimagine_button)
    tools_layout.addWidget(strength_widget)
    tools_layout.addWidget(steps_widget)
    tools_layout.addWidget(guidance_widget)
    # tools_layout.addWidget(inpaint_selector_container)
    tools_layout.addWidget(quicksave_button)
    tools_layout.addWidget(export_button)
    tools_layout.addWidget(increase_size_container)
    tools_layout.addWidget(scratchpad_container)
    tools_widget.setLayout(tools_layout)

    load_image_button.clicked.connect(lambda : handle_load_image_button(widget))
    erase_button.clicked.connect(lambda : handle_erase_button(widget))
    undo_button.clicked.connect(lambda : handle_undo_button(widget))
    redo_button.clicked.connect(lambda : handle_redo_button(widget))
    generate_button.clicked.connect(lambda : handle_generate_button(widget, stable_diffusion_handler, prompt_textarea.text()))
    inpaint_button.clicked.connect(lambda : handle_inpaint_button(widget, stable_diffusion_handler, prompt_textarea.text()))
    quicksave_button.clicked.connect(lambda : handle_quicksave_button(widget))
    export_button.clicked.connect(lambda : handle_export_button(widget))
    select_color_button.clicked.connect(lambda : handle_select_color_button(widget, select_color_button))
    paint_button.clicked.connect(lambda : handle_paint_button(widget))
    increase_size_button.clicked.connect(lambda : handle_increase_size_button(widget))
    decrease_size_button.clicked.connect(lambda : handle_decrease_size_button(widget))
    show_scratchpad_button.clicked.connect(lambda : handle_show_scratchpad(widget, scratchpad))
    paste_scratchpad_button.clicked.connect(lambda : handle_paste_scratchpad(widget, scratchpad))
    reimagine_button.clicked.connect(lambda : handle_reimagine_button(widget, stable_diffusion_handler, prompt_textarea.text()))

    widget.set_np_image(testtexture)
    widget.resize_to_image()
    widget.show()
    tools_widget.show()
    app.exec()