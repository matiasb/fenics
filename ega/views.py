# -*- coding: utf-8 -*-

from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.forms.models import modelformset_factory
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.timezone import now
from django.views.decorators.http import require_GET, require_http_methods

from ega.constants import (
    EXACTLY_MATCH_POINTS,
    HISTORY_MATCHES_PER_PAGE,
    HOURS_TO_DEADLINE,
    INVITE_BODY,
    INVITE_LEAGUE,
    INVITE_SUBJECT,
    NEXT_MATCHES_DAYS,
    RANKING_TEAMS_PER_PAGE,
)
from ega.forms import (
    EgaUserForm,
    InviteFriendsForm,
    LeagueForm,
    PredictionForm,
)
from ega.models import (
    EgaUser,
    League,
    LeagueMember,
    Match,
    Prediction,
    Tournament,
)


def build_invite_url(request, slug, key=None, league_slug=None):
    if key is None:
        key = request.user.invite_key

    kwargs = dict(key=key, slug=slug)
    if league_slug is not None:
        kwargs['league_slug'] = league_slug

    return request.build_absolute_uri(reverse('ega-join', kwargs=kwargs))


def logout(request):
    auth.logout(request)
    messages.success(request, 'Cerraste sesión exitosamente!')
    return HttpResponseRedirect(reverse('meta-home'))


def _next_matches(user):
    tz_now = now() + timedelta(hours=HOURS_TO_DEADLINE)
    until = tz_now + timedelta(days=NEXT_MATCHES_DAYS)
    matches = Match.objects.select_related('tournament').filter(
        tournament__published=True, tournament__finished=False,
        when__range=(tz_now, until)).order_by('tournament', 'when')
    predictions = user.prediction_set.filter(
        match__in=matches, home_goals__isnull=False, away_goals__isnull=False)
    next_matches = []
    for m in matches:
        pred = None
        for p in predictions:
            if p.match == m:
                pred = p
                break
        row = {'match': m, 'prediction': pred}
        next_matches.append(row)
    return next_matches


@login_required
def meta_home(request):
    past_tournaments = Tournament.objects.filter(
        published=True, finished=True).order_by('-id')
    next_matches = _next_matches(request.user)
    return render(request, 'ega/meta_home.html',
                  {'next_matches': next_matches,
                   'past_tournaments': past_tournaments})


@login_required
def home(request, slug):
    tournament = get_object_or_404(Tournament, slug=slug, published=True)
    matches = tournament.next_matches()
    played = Prediction.objects.filter(
        user=request.user, match__in=matches,
        home_goals__isnull=False, away_goals__isnull=False)
    pending = Prediction.objects.filter(
        Q(home_goals__isnull=True) | Q(away_goals__isnull=True),
        user=request.user, match__in=matches).first()

    current_round = tournament.current_round()
    matches = matches[:3]
    for m in matches:
        try:
            m.user_prediction = played.get(match=m)
        except Prediction.DoesNotExist:
            m.user_prediction = None

    top_ranking = tournament.ranking()[:7]
    history = request.user.history(tournament)[:3]
    stats = request.user.stats(tournament)

    return render(
        request, 'ega/home.html',
        {'top_ranking': top_ranking,
         'tournament': tournament, 'current_round': current_round,
         'pending': pending, 'matches': matches, 'history': history,
         'stats': stats})


@require_http_methods(('GET', 'POST'))
@login_required
def profile(request):
    if request.method == 'POST':
        form = EgaUserForm(
            instance=request.user, data=request.POST, files=request.FILES)
        if form.is_valid():
            form.save()
            messages.success(
                request, 'Perfil actualizado.')
            return HttpResponseRedirect(reverse('profile'))
    else:
        form = EgaUserForm(instance=request.user)
    return render(request, 'ega/profile.html', dict(form=form))


@require_http_methods(('GET', 'POST'))
@login_required
def invite_friends(request, slug, league_slug=None):
    tournament = get_object_or_404(Tournament, slug=slug, published=True)

    league = None
    if league_slug:
        league = get_object_or_404(
            League, tournament=tournament, slug=league_slug)
        if league.owner != request.user:
            raise Http404
    invite_url = build_invite_url(
        request, slug=tournament.slug, league_slug=league_slug)

    if request.method == 'POST':
        form = InviteFriendsForm(request.POST)
        if form.is_valid():
            emails = form.invite(sender=request.user)
            if emails > 1:
                msg = '%s amigos invitados!' % emails
            else:
                msg = '1 amigo invitado!'
            messages.success(request, msg)
            return HttpResponseRedirect(reverse('ega-home', args=[slug]))
    else:
        subject = INVITE_SUBJECT
        extra_text = ''
        if league:
            subject += ', jugando en mi liga de amigos %s' % league.name
            extra_text = INVITE_LEAGUE % dict(league_name=league.name)

        initial = dict(
            subject=subject,
            body=INVITE_BODY % dict(
                extra_text=extra_text, url=invite_url,
                inviter=request.user.visible_name()),
        )
        form = InviteFriendsForm(initial=initial)

    return render(request, 'ega/invite.html',
                  dict(tournament=tournament, form=form,
                       league=league, invite_url=invite_url))


@require_GET
@login_required
def friend_join(request, key, slug, league_slug=None):
    inviting_user = get_object_or_404(EgaUser, invite_key=key)
    if inviting_user == request.user:
        invite_url = build_invite_url(
            request, slug=slug, league_slug=league_slug)
        msg1 = 'Vos sos el dueño del link %s!' % invite_url
        msg2 = 'No podés unirte con un link de referencia propio.'
        messages.info(request, msg1)
        messages.warning(request, msg2)
        return HttpResponseRedirect(reverse('ega-home', args=[slug]))

    created = inviting_user.record_referral(request.user)
    if created:
        msg = 'Te uniste a el Ega! '
    else:
        msg = 'Hola de nuevo! '

    if league_slug:
        league = get_object_or_404(
            League, tournament__slug=slug, slug=league_slug)
        member, created = LeagueMember.objects.get_or_create(
            user=request.user, league=league)
        if created:
            msg += 'Bienvenido a la liga %s.' % league
        else:
            msg += 'Ya sos miembro de la liga %s.' % league

    messages.success(request, msg)
    # switch to the tournament this user was invited to
    return HttpResponseRedirect(reverse('ega-home', kwargs=dict(slug=slug)))


@require_http_methods(('GET', 'POST'))
@login_required
def leagues(request, slug):
    tournament = get_object_or_404(Tournament, slug=slug, published=True)

    if request.method == 'POST':
        form = LeagueForm(request.POST)
        if form.is_valid():
            league = form.save(commit=False)
            league.tournament = tournament
            league.save()
            LeagueMember.objects.create(
                user=request.user, league=league, is_owner=True)
            return HttpResponseRedirect(
                reverse('ega-invite-league',
                        kwargs=dict(slug=slug, league_slug=league.slug)))
    else:
        form = LeagueForm()

    user_leagues = League.objects.filter(
        tournament=tournament, members=request.user)
    return render(
        request, 'ega/leagues.html',
        dict(tournament=tournament, leagues=user_leagues, form=form))


@require_GET
@login_required
def league_home(request, slug, league_slug):
    tournament = get_object_or_404(Tournament, slug=slug, published=True)
    league = get_object_or_404(
        League, slug=league_slug, members=request.user,
        tournament=tournament, tournament__published=True)

    top_ranking = league.ranking()[:5]
    stats = request.user.stats(tournament)

    return render(
        request, 'ega/league_home.html',
        {'tournament': tournament, 'league': league,
         'top_ranking': top_ranking, 'stats': stats})


@login_required
def next_matches(request, slug):
    """Return coming matches for the specified tournament."""
    tournament = get_object_or_404(Tournament, slug=slug, published=True)
    matches = tournament.next_matches()
    for m in matches:
        # create prediction for user if missing
        Prediction.objects.get_or_create(
            user=request.user, match=m, defaults={'starred': m.starred})

    PredictionFormSet = modelformset_factory(
        Prediction, form=PredictionForm, extra=0)
    predictions = Prediction.objects.filter(
        user=request.user, match__in=matches)

    if request.method == 'POST':
        formset = PredictionFormSet(request.POST)
        if formset.is_valid():
            formset.save()
            messages.success(request, 'Pronósticos actualizados.')

            expired_matches = [f.instance.match for f in formset if f.expired]
            for m in expired_matches:
                msg = "%s - %s: el partido expiró, pronóstico NO actualizado."
                messages.error(request, msg % (m.home.name, m.away.name))

            return HttpResponseRedirect(reverse('ega-home', args=[slug]))

    else:
        formset = PredictionFormSet(queryset=predictions)

    return render(request, 'ega/next_matches.html',
                  {'tournament': tournament, 'formset': formset})


@login_required
def match_details(request, slug, match_id):
    """Return specified match stats."""
    tournament = get_object_or_404(Tournament, slug=slug, published=True)
    match = get_object_or_404(
        Match, id=match_id, tournament=tournament, tournament__published=True)

    exacts = Prediction.objects.none()
    winners = Prediction.objects.none()
    if match.finished:
        winners = Prediction.objects.filter(
            match=match, score__gt=0, score__lt=EXACTLY_MATCH_POINTS)
        exacts = Prediction.objects.filter(
            match=match, score__gte=EXACTLY_MATCH_POINTS
        ).select_related('user')

    return render(
        request, 'ega/match_details.html',
        {'tournament': tournament, 'match': match,
         'exacts': exacts, 'winners': winners})


@login_required
def ranking(request, slug, league_slug=None, round=None):
    """Return ranking and stats for the specified tournament."""
    tournament = get_object_or_404(Tournament, slug=slug, published=True)
    league = None

    base_url = reverse('ega-ranking', args=[slug])
    if league_slug is not None:
        base_url = reverse('ega-league-ranking',
                           args=[tournament.slug, league_slug])
        league = get_object_or_404(
            League, tournament=tournament, tournament__published=True,
            slug=league_slug)

    user = request.user
    scores = (league.ranking(round=round)
              if league else tournament.ranking(round=round))
    try:
        position = ([r['username'] for r in scores]).index(user.username)
        position += 1
    except ValueError:
        position = None
    paginator = Paginator(scores, RANKING_TEAMS_PER_PAGE)

    page = request.GET.get('page')
    try:
        ranking = paginator.page(page)
    except PageNotAnInteger:
        ranking = paginator.page(1)
    except EmptyPage:
        ranking = paginator.page(paginator.num_pages)

    stats = user.stats(tournament, round=round)
    round_choices = tournament.match_set.filter(
        home_goals__isnull=False, away_goals__isnull=False).values_list(
        'round', flat=True).order_by('round').distinct()
    user_leagues = League.objects.filter(
        tournament=tournament, members=request.user)

    return render(
        request, 'ega/ranking.html',
        {'tournament': tournament, 'league': league, 'leagues': user_leagues,
         'base_url': base_url, 'round': round, 'choices': round_choices,
         'ranking': ranking, 'user_position': position, 'stats': stats})


@login_required
def history(request, slug):
    """Return history for the specified tournament."""
    tournament = get_object_or_404(Tournament, slug=slug, published=True)
    user_history = request.user.history(tournament)
    paginator = Paginator(user_history, HISTORY_MATCHES_PER_PAGE)

    page = request.GET.get('page')
    try:
        predictions = paginator.page(page)
    except PageNotAnInteger:
        predictions = paginator.page(1)
    except EmptyPage:
        predictions = paginator.page(paginator.num_pages)

    stats = request.user.stats(tournament)

    return render(
        request, 'ega/history.html',
        {'tournament': tournament, 'predictions': predictions, 'stats': stats})


def stats(request, slug):
    """Return stats for the specified tournament."""
    tournament = get_object_or_404(Tournament, slug=slug, published=True)

    results = tournament.most_common_results(5)
    predictions = tournament.most_common_predictions(5)
    ranking = tournament.team_ranking()

    no_wins = [r.team for r in ranking if r.won == 0]
    no_ties = [r.team for r in ranking if r.tie == 0]
    no_loses = [r.team for r in ranking if r.lost == 0]

    return render(
        request, 'ega/stats.html',
        {'tournament': tournament, 'ranking': ranking,
         'top_5': zip(results, predictions),
         'no_wins': no_wins, 'no_ties': no_ties, 'no_loses': no_loses})


@login_required
def verify_email(request, email):
    email_address = get_object_or_404(
        EmailAddress, user=request.user, email=email)
    email_address.send_confirmation(request)
    messages.success(request, 'Email de verificación enviado a %s' % email)
    return HttpResponseRedirect(reverse('profile'))
