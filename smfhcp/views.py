from django.shortcuts import render, redirect
from django.views.decorators.cache import cache_control
from django.contrib.auth import logout as logout_user
import elasticsearch
from elasticsearch import Elasticsearch
import hashlib
from django.core.mail import send_mail
from django.conf import settings
from random import randint
import json
from django.http import HttpResponse
from django.core.exceptions import PermissionDenied
from django.contrib import messages
import datetime
import re
import pytz
import textile

es = Elasticsearch(hosts=['192.168.116.82'])


def random_with_n_digits(n):
    range_start = 10**(n-1)
    range_end = (10**n)-1
    return randint(range_start, range_end)


def base_view(request):
    return render(request, 'smfhcp/home.html')


def handler404(request, exception):
    return render(request, 'smfhcp/404.html', status=404)


def handler500(request):
    return render(request, 'smfhcp/500.html', status=500)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def index(request):
    request.session['user_name'] = request.user.username
    request.session['email'] = request.user.email
    request.session['is_authenticated'] = True
    request.session['is_doctor'] = False
    try:
        es.get(index='general-user', id=request.user.username)
    except elasticsearch.NotFoundError:
        body = {
            "user_name": request.user.username,
            "email": request.user.email,
            "follow_list": []
        }
        index_user(body)
    return redirect('/')


def index_user(body):
    if 'password_hash' in body:
        query_body = {
            "query": {
                "match": {
                    "email": body['email']
                }
            }
        }
        res = es.search(index=['general-user', 'doctor'], body=query_body)
        if res['hits']['total']['value'] > 0:
            return False
        try:
            es.get(index='general-user', id=body['user_name'])
        except elasticsearch.NotFoundError:
            try:
                res_doctor = es.get(index=['doctor'], id=body['user_name'])
            except elasticsearch.NotFoundError:
                es.index(index='general-user', id=body['user_name'], body=body)
                return True
            return False
        return False
    else:
        es.index(index='general-user', id=body['user_name'], body=body)


def find_user(user_name):
    try:
        res_user = es.get(index=['general-user'], id=user_name)
        return res_user['_source'], False
    except elasticsearch.NotFoundError:
        try:
            res_doctor = es.get(index=['doctor'], id=user_name)
            return res_doctor['_source'], True
        except elasticsearch.NotFoundError:
            return None, None


def find_hash(input):
    return hashlib.sha256(str(input).encode('utf-8')).hexdigest()


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def signup_email(request):
    if request.method == 'POST':
        data = request.POST.copy()
        body = {
            "user_name": data.get('user_name'),
            "email": data.get('email'),
            "password_hash": find_hash(data.get('password')),
            "follow_list": []
        }
        if index_user(body) is False:
            response_data = {
                "message": 'User name or email already exists.'
            }
            return HttpResponse(
                json.dumps(response_data),
                content_type="application/json"
            )
        request.session['user_name'] = data.get('user_name')
        request.session['email'] = data.get('email')
        request.session['is_authenticated'] = True
        request.session['is_doctor'] = False
        response_data = {
            "redirect": True,
            "redirect_url": "/"
        }
        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        raise PermissionDenied()


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def login_user(request):
    if request.method == 'POST':
        data = request.POST.copy()
        res, is_doctor = find_user(data.get('user_name'))
        if res is not None and find_hash(data.get('password')) == res['password_hash']:
            request.session['user_name'] = res['user_name']
            request.session['email'] = res['email']
            request.session['is_authenticated'] = True
            if is_doctor is True:
                request.session['is_doctor'] = True
            else:
                request.session['is_doctor'] = False
            response_data = {
                "redirect": True,
                "redirect_url": "/"
            }
            return HttpResponse(
                json.dumps(response_data),
                content_type="application/json"
            )
        else:
            response_data = {
                "message": 'Username/Password does not match.'
            }
            return HttpResponse(
                json.dumps(response_data),
                content_type="application/json"
            )
    else:
        raise PermissionDenied()


def check_email_existence(email_id):
    query_body = {
        "query": {
            "match": {
                "email": email_id
            }
        }
    }
    res = es.search(index=['general-user', 'doctor'], body=query_body)
    if res['hits']['total']['value'] > 0:
        return False, "User already exists."
    try:
        es.get(index='doctor-activation', id=email_id)
        return False, "User already invited."
    except elasticsearch.NotFoundError:
        return True, "Sent Invite"


def send_invitation_email(receiver_email, token):
    subject = "Invitation to join SMFHCP as a Health care Professional"
    message = "Please open this link http://127.0.0.1:8000/doctor_signup/{} to join SMFHCP.\n".format(token)
    try:
        send_mail(subject, from_email=settings.EMAIL_HOST_USER,
                  recipient_list=[receiver_email], message=message, fail_silently=False)
        return True
    except Exception:
        print("Error in sending mail")
        return False


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def send_invite(request):
    email_id = request.POST.get('email')
    token = random_with_n_digits(6)
    print(token)
    valid, message = check_email_existence(email_id)
    if valid is True:
        res = send_invitation_email(email_id, token)
        if res is True:
            body = {
                "email": email_id,
                "token": token
            }
            es.index(index='doctor-activation', id=email_id, body=body)
            response_data = {
                "message": 'Invitation sent successfully.',
                "success": True
            }
            return HttpResponse(
                json.dumps(response_data),
                content_type="application/json"
            )
        else:
            response_data = {
                "message": 'Could not send email.',
                "success": False
            }
            return HttpResponse(
                json.dumps(response_data),
                content_type="application/json"
            )
    else:
        response_data = {
            "message": message,
            "success": False
        }
        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def doctor_signup(request, otp):
    print(otp)
    if "is_authenticated" not in request.session or request.session['is_authenticated'] is False:
        messages.info(request, otp)
    return render(request, 'smfhcp/doctor_create_profile.html')


def index_doctor(request, res, data):
    request.session['user_name'] = data.get('user_name')
    request.session['email'] = data.get('email')
    request.session['is_authenticated'] = True
    request.session['is_doctor'] = True
    body = {
        "user_name": data.get('user_name'),
        "email": data.get('email'),
        "password_hash": find_hash(data.get('password')),
        "full_name": data.get('firstName') + ' ' + data.get('lastName'),
        "qualification": [s.strip() for s in json.loads(data.get('qualification'))['qualifications']],
        "research_interests": [s.strip() for s in json.loads(data.get('researchInterests'))['researchInterests']],
        "profession": data.get('profession'),
        "institution": data.get('institution'),
        "clinical_interests": [s.strip() for s in json.loads(data.get('clinicalInterests'))['clinicalInterests']],
        "follow_list": [],
        "follower_count": 0,
        "post_count": 0,
        "posts": []
    }
    es.index(index='doctor', id=body['user_name'], body=body)


def create_profile(request):
    if request.method == 'POST':
        data = request.POST.copy()
        res, _ = find_user(data.get('user_name'))
        if res is None:
            try:
                res = es.get(index='doctor-activation', id=data.get('email'))
                if str(res['_source']['token']) == str(data.get('otp')):
                    index_doctor(request, res, data)
                    response_data = {
                        "redirect": True,
                        "redirect_url": "/"
                    }
                    return HttpResponse(
                        json.dumps(response_data),
                        content_type="application/json"
                    )
                else:
                    response_data = {
                        "message": 'OTP, email pair do not match.'
                    }
                    return HttpResponse(
                        json.dumps(response_data),
                        content_type="application/json"
                    )
            except elasticsearch.NotFoundError:
                response_data = {
                    "message": 'This email id does not have an invite.'
                }
                return HttpResponse(
                    json.dumps(response_data),
                    content_type="application/json"
                )
        else:
            response_data = {
                "message": 'Username already exists.'
            }
            return HttpResponse(
                json.dumps(response_data),
                content_type="application/json"
            )
    else:
        raise PermissionDenied()


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def view_profile(request, user_name):
    if request.session['is_authenticated']:
        res_doctor = es.get(index=['doctor'], id=user_name)
        query_body = {
            "query": {
                "match": {
                    "user_name": user_name
                }
            }
        }
        posts = True
        res = es.search(index=['post'], body=query_body)
        post_list = res['hits']['hits']
        for post in post_list:
            string = re.sub("\+(?P<hour>\d{2}):(?P<minute>\d{2})$", "+\g<hour>\g<minute>", post['_source']['date'])
            dt = datetime.datetime.strptime(string, "%Y-%m-%dT%H:%M:%S.%f%z")
            dt = dt.astimezone(pytz.UTC)
            post['_source']['date'] = pretty_date(dt)
        if res['hits']['total']['value'] == 0:
            posts = False
        is_following = find_if_follows(request, user_name)
        context = {
            'user_name': res_doctor['_source']['user_name'],
            'full_name': res_doctor['_source']['full_name'],
            'email': res_doctor['_source']['email'],
            'qualification': res_doctor['_source']['qualification'],
            'research_interests': res_doctor['_source']['research_interests'],
            'profession': res_doctor['_source']['profession'],
            'institution': res_doctor['_source']['institution'],
            'clinical_interests': res_doctor['_source']['clinical_interests'],
            'following_count': len(res_doctor['_source']['follow_list']),
            'post_count': res_doctor['_source']['post_count'],
            'follower_count': res_doctor['_source']['follower_count'],
            'posts_available': posts,
            'posts': post_list,
            'isFollowing': is_following
        }
        return render(request, 'smfhcp/view_profile.html', context)
    else:
        return redirect("/")


def build_inline_string(data):
    inline_string = ""
    params = {}
    if data.get('password') is not None:
        inline_string += "ctx._source.password_hash = params.password_hash; "
        params['password_hash'] = str(find_hash(data.get('password')))
    if len(json.loads(data.get('qualification'))['qualifications']) > 0:
        inline_string += "ctx._source.qualification.addAll(params.qualification); "
        params['qualification'] = [s.strip() for s in json.loads(data.get('qualification'))['qualifications']]
    if str(data.get('profession')) != '':
        inline_string += "ctx._source.profession = params.profession; "
        params['profession'] = str(data.get('profession'))
    if str(data.get('institution')) != '':
        inline_string += "ctx._source.institution = params.institution; "
        params['institution'] = str(data.get('institution'))
    if len(json.loads(data.get('researchInterests'))['researchInterests']) > 0:
        inline_string += "ctx._source.research_interests.addAll(params.research_interests); "
        params['research_interests'] = [s.strip() for s in json.loads(data.get('researchInterests'))['researchInterests']]
    if len(json.loads(data.get('clinicalInterests'))['clinicalInterests']) > 0:
        inline_string += "ctx._source.clinical_interests.addAll(params.clinical_interests); "
        params['clinical_interests'] = [s.strip() for s in json.loads(data.get('clinicalInterests'))['clinicalInterests']]
    return inline_string, params


def update_document(inline_string, params, index_name, doc_id):
    body = {
        "script": {
            "inline": inline_string,
            "lang": "painless",
            "params": params
        }
    }
    es.update(index=index_name, id=doc_id, body=body)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def update_profile(request):
    if request.method == 'POST':
        inline_string, params = build_inline_string(request.POST)
        update_document(inline_string, params, 'doctor', str(request.session['user_name']))
        response_data = {
            'redirect': True,
            'redirect_url': '/view_profile/' + str(request.session['user_name'])
        }
        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        PermissionDenied()


def index_post(request, data, post_type_case_study=True):
    res = es.get(index='doctor', id=request.session['user_name'])
    print(request.session['user_name'])
    print(res)
    body = {
        "user_name": request.session['user_name'],
        "full_name": res['_source']['full_name'],
        "profession": res['_source']['profession'],
        "institution": res['_source']['institution'],
        "view_count": 1,
        "title": data.get('title'),
        "tags": [str(s).strip() for s in json.loads(data.get('tags'))['tags']],
        "date": datetime.datetime.now(datetime.timezone.utc),
        "comments": []
    }
    if post_type_case_study:
        body['history'] = textile.textile(data.get('history'))
        body['diagnosis'] = textile.textile(data.get('diagnosis'))
        body['examination'] = textile.textile(data.get('examination'))
        body['prevention'] = textile.textile(data.get('prevention'))
        body['treatment'] = textile.textile(data.get('treatment'))
        body['remarks'] = textile.textile(data.get('remarks'))
    else:
        body['description'] = textile.textile(data.get('description'))
    res = es.index(index='post', body=body)
    return res['_id']


def pretty_date(time):
    now = datetime.datetime.now(datetime.timezone.utc)
    diff = now - time
    second_diff = diff.seconds
    day_diff = diff.days
    if day_diff < 0:
        return ''
    elif day_diff == 0:
        if second_diff < 10:
            return "just now"
        if second_diff < 60:
            return str(second_diff) + " seconds ago"
        if second_diff < 120:
            return "a minute ago"
        if second_diff < 3600:
            return str(second_diff // 60) + " minutes ago"
        if second_diff < 7200:
            return "an hour ago"
        if second_diff < 86400:
            return str(second_diff // 3600) + " hours ago"
    elif day_diff == 1:
        return "Yesterday"
    elif 30 <= day_diff < 365:
        return "{} months ago".format(day_diff // 30)
    elif 1 < day_diff < 30:
        return "{} days ago".format(day_diff)
    return "{} years ago".format(day_diff // 365)


def find_if_follows(request, doctor_user_name):
    if request.session['is_doctor']:
        res = es.get(index='doctor', id=request.session['user_name'])
        if "follow_list" in res["_source"] and str(doctor_user_name) in res["_source"]["follow_list"]:
            return True
    else:
        res = es.get(index='general-user', id=request.session['user_name'])
        if "follow_list" in res["_source"] and str(doctor_user_name) in res["_source"]["follow_list"]:
            return True
    return False


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def view_post(request, post_id):
    if request.session['is_authenticated']:
        res = es.get(index='post', id=post_id)
        string = re.sub("\+(?P<hour>\d{2}):(?P<minute>\d{2})$", "+\g<hour>\g<minute>", res['_source']['date'])
        dt = datetime.datetime.strptime(string, "%Y-%m-%dT%H:%M:%S.%f%z")
        dt = dt.astimezone(pytz.UTC)
        res['_source']['date'] = pretty_date(dt)
        res["_source"]['isFollowing'] = find_if_follows(request, res['_source']['user_name'])
        res["_source"]['post_id'] = post_id
        update_post_view_count(post_id)
        return render(request, 'smfhcp/view_post.html', res['_source'])
    else:
        return redirect("/")


def update_post_count(request):
    body = {
        "script": {
            "source": "ctx._source.post_count += params.count",
            "lang": "painless",
            "params": {
                "count": 1
            }
        }
    }
    es.update(index='doctor', id=request.session['user_name'], body=body)


def update_post_view_count(post_id):
    body = {
        "script": {
            "source": "ctx._source.view_count += params.count",
            "lang": "painless",
            "params": {
                "count": 1
            }
        }
    }
    es.update(index='post', id=post_id, body=body)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def create_case_study(request):
    if request.method == 'POST':
        data = request.POST.copy()
        post_id = index_post(request, data)
        update_post_count(request)
        response_data = {
            'redirect': True,
            'redirect_url': '/view_post/' + str(post_id)
        }
        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        PermissionDenied()


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def create_general_post(request):
    if request.method == 'POST':
        data = request.POST.copy()
        post_id = index_post(request, data, False)
        update_post_count(request)
        response_data = {
            'redirect': True,
            'redirect_url': '/view_post/' + str(post_id)
        }
        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        PermissionDenied()


def update_follow_count(data):
    body = {
        "script": {
            "lang": "painless",
            "params": {
                "count": 1
            }
        }
    }
    if data.get('follow') == "true":
        body['script']['source'] = "ctx._source.follower_count += params.count"
    else:
        body['script']['source'] = "if(ctx._source.follower_count > 0) {ctx._source.follower_count -= params.count}"
    es.update(index='doctor', id=data.get('doctor_name'), body=body)


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def follow_or_unfollow(request):
    if request.method == 'POST':
        data = request.POST.copy()
        body = {}
        if data.get('follow') == "true":
            print("here")
            body = {
                "script": {
                    "inline": "ctx._source.follow_list.add(params.doctor_user_name);",
                    "lang": "painless",
                    "params": {
                        "doctor_user_name": data.get('doctor_name')
                    }
                }
            }
            print("follow")
        else:
            body = {
                "script": {
                    "source": "ctx._source.follow_list.remove(ctx._source.follow_list.indexOf(params.doctor_user_name))",
                    "lang": "painless",
                    "params": {
                        "doctor_user_name": data.get('doctor_name')
                    }
                }
            }
        if request.session['is_doctor']:
            es.update(index='doctor', id=request.session['user_name'], body=body)
        else:
            es.update(index='general-user', id=request.session['user_name'], body=body)
        update_follow_count(data)
        return HttpResponse(
            json.dumps({}),
            content_type="application/json"
        )
    else:
        PermissionDenied()


def add_comment(request):
    if request.method == 'POST':
        body = {
            "script": {
                "source": "ctx._source.comments.add(params.new_comment)",
                "lang": "painless",
                "params": {
                    "new_comment": {
                        "comment_body": request.POST.get('comment_text'),
                        "user_name": request.POST.get('user_name'),
                        "replies": [],
                        "comment_id": find_hash(datetime.datetime.now())
                    }
                }
            }
        }
        es.update(index='post', id=request.POST.get('post_id'), body=body)
        return HttpResponse(
            json.dumps({}),
            content_type="application/json"
        )
    else:
        PermissionDenied()


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def logout(request):
    logout_user(request)
    request.session['user_name'] = None
    request.session['email'] = None
    request.session['is_authenticated'] = False
    request.session['is_doctor'] = None
    request.session.modified = True
    return redirect('/')
