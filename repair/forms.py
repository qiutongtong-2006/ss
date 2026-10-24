from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Building, RepairCategory, User, WorkOrder


class StudentRegistrationForm(UserCreationForm):
    real_name = forms.CharField(label='姓名', max_length=30)
    phone = forms.CharField(label='联系电话', max_length=20, required=False)

    class Meta:
        model = User
        fields = ('username', 'real_name', 'phone')
        labels = {'username': '学号'}
        help_texts = {'username': '请使用学号注册，注册后用它登录。'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['username'].widget.attrs['placeholder'] = '请输入学号'
        self.fields['real_name'].widget.attrs['placeholder'] = '请输入真实姓名'
        self.fields['phone'].widget.attrs['placeholder'] = '选填，方便维修人员联系'

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('该学号已注册，请直接登录。')
        return username


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """接收一个或多个图片文件，返回文件列表。"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            'widget',
            MultipleImageInput(attrs={'accept': 'image/*', 'multiple': True}),
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if isinstance(data, (list, tuple)):
            if not data:
                return []
            return [super(MultipleImageField, self).clean(item, initial) for item in data]
        if not data:
            return []
        return [super(MultipleImageField, self).clean(data, initial)]


class WorkOrderSubmitForm(forms.ModelForm):
    building = forms.ModelChoiceField(
        label='楼栋',
        queryset=Building.objects.none(),
        empty_label='请选择楼栋',
        help_text='楼栋由宿管在管理后台统一维护。',
    )
    repair_address = forms.CharField(
        label='维修地址',
        max_length=200,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': '选填，例如 302 卫生间洗手台下方',
            }
        ),
        help_text='填写更具体的位置，方便维修人员上门。',
    )
    contact_phone = forms.CharField(
        label='联系电话',
        max_length=20,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': '维修人员联系你的电话',
            }
        ),
    )
    remark = forms.CharField(
        label='备注（选填）',
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '例如：只有晚上 7 点后有人；进门请先敲门；故障位置在阳台',
            }
        ),
        help_text='其他需要告知维修人员的信息。',
    )
    allow_entry_without_student = forms.BooleanField(
        label='宿舍无人时，同意维修人员在宿管陪同下进入宿舍维修',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text='未勾选时，宿管会通过你填写的联系电话与你约定上门时间。',
    )
    images = MultipleImageField(
        label='现场照片（选填）',
        required=False,
        help_text='建议上传 1～3 张，每张不超过 5 MB，支持 JPG、PNG 等常见格式。',
    )

    class Meta:
        model = WorkOrder
        fields = (
            'room_no',
            'repair_address',
            'contact_phone',
            'category',
            'description',
            'remark',
            'allow_entry_without_student',
        )
        field_order = [
            'building',
            'room_no',
            'repair_address',
            'contact_phone',
            'category',
            'description',
            'images',
            'remark',
            'allow_entry_without_student',
        ]
        labels = {
            'room_no': '房间号',
            'category': '报修类别',
            'description': '故障描述',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user and not self.is_bound:
            self.initial.setdefault('contact_phone', user.phone)
        self.fields['building'].queryset = Building.objects.filter(
            is_active=True
        ).order_by('name')
        self.fields['building'].widget.attrs['class'] = 'form-select'
        self.fields['category'].queryset = RepairCategory.objects.filter(is_active=True)
        self.fields['category'].empty_label = '请选择报修类别'
        self.fields['category'].widget.attrs['class'] = 'form-select'
        self.fields['room_no'].widget.attrs.update(
            {'class': 'form-control', 'placeholder': '例如 302'}
        )
        self.fields['description'].widget.attrs.update(
            {
                'class': 'form-control',
                'rows': 4,
                'placeholder': '请描述故障现象、位置和方便上门的时间',
            }
        )

    def clean_images(self):
        images = self.cleaned_data.get('images', [])
        if not images:
            return []
        if len(images) > 3:
            raise forms.ValidationError('最多上传 3 张照片。')
        for image in images:
            if image.size > 5 * 1024 * 1024:
                raise forms.ValidationError(f'照片 {image.name} 超过 5 MB。')
        return images


class RejectOrderForm(forms.Form):
    reason = forms.CharField(
        label='驳回原因',
        max_length=500,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': '请说明驳回原因，学生会在工单详情中看到',
            }
        ),
    )


class CancelOrderForm(forms.Form):
    reason = forms.CharField(
        label='撤销原因（选填）',
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '如果愿意，可以说明撤销原因',
            }
        ),
    )


class AcceptOrderForm(forms.Form):
    repairer = forms.ModelChoiceField(
        label='维修人员',
        queryset=User.objects.none(),
        empty_label='请选择维修人员',
    )
    contact_note = forms.CharField(
        label='联系备注（选填）',
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '例如：已电话联系，约定周六上午上门',
            }
        ),
        help_text='学生未授权入室时，建议记录联系结果。',
    )
    appointment_at = forms.DateTimeField(
        label='约定上门时间（选填）',
        required=False,
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(
            attrs={'class': 'form-control', 'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M',
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['repairer'].queryset = User.objects.filter(
            role=User.Role.REPAIRER,
            is_active=True,
        ).order_by('username')
        self.fields['repairer'].widget.attrs['class'] = 'form-select'


class RepairCompletionForm(forms.Form):
    fault_cause = forms.CharField(
        label='故障原因（选填）',
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '例如：水龙头阀芯老化导致持续漏水',
            }
        ),
    )
    repair_action = forms.CharField(
        label='维修内容（必填）',
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': '请填写实际处理措施和维修结果',
            }
        ),
        help_text='说明如何完成维修，作为本工单的维修记录。',
    )
    materials_used = forms.CharField(
        label='更换材料（选填）',
        required=False,
        max_length=500,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': '例如：阀芯 1 个、密封圈 2 个；未更换材料可留空',
            }
        ),
    )


class AcceptanceEvaluationForm(forms.Form):
    rating = forms.TypedChoiceField(
        label='维修满意度',
        choices=[
            (1, '1 星 · 很不满意'),
            (2, '2 星 · 不满意'),
            (3, '3 星 · 一般'),
            (4, '4 星 · 满意'),
            (5, '5 星 · 非常满意'),
        ],
        coerce=int,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
    )
    comment = forms.CharField(
        label='评价内容',
        max_length=1000,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': '请描述维修效果、响应速度或需要改进的地方',
            }
        ),
        help_text='评价提交后不能修改。',
    )


class AcceptanceReturnForm(forms.Form):
    reason = forms.CharField(
        label='退回原因',
        max_length=500,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': '请说明故障仍然存在或尚未解决的问题',
            }
        ),
    )
