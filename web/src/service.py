import random
import networkx as nx
import numpy as np
from geopy.geocoders import Nominatim
import flask
import flask_bootstrap
import flask_wtf
import wtforms.fields.html5
import wtforms.validators
import flask_ngrok

app = flask.Flask(__name__, static_folder='../static', template_folder='../templates')
app.config['SECRET_KEY'] = ''
flask_bootstrap.Bootstrap(app)
flask_ngrok.run_with_ngrok(app)
google_api_key = ''
hadar_graph = nx.read_gml('hadar.gml')
geocoder = Nominatim(user_agent="Hadar Maps")


class RouteForm(flask_wtf.FlaskForm):
    source = wtforms.TextField('', [wtforms.validators.InputRequired()])
    destination = wtforms.TextField('', [wtforms.validators.InputRequired()])
    stairs = wtforms.fields.html5.IntegerRangeField('', default=1)
    slopes = wtforms.fields.html5.IntegerRangeField('', default=1)
    safety = wtforms.fields.html5.IntegerRangeField('', default=1)
    com_parks = wtforms.BooleanField('', default=0)
    sport_parks = wtforms.BooleanField('', default=0)
    sport_route = wtforms.BooleanField('', default=0)
    route_km = wtforms.fields.html5.DecimalRangeField('', default=0)
    submit = wtforms.SubmitField('')


@app.route('/', methods=['GET', 'POST'])
@app.route('/<string:language>', methods=['GET', 'POST'])
def index(language=None):
    print(language)
    if language is None or language not in ['en', 'ru', 'he', 'ar']:
        return flask.redirect('/en')
    form = RouteForm()
    route_string = f'https://www.google.com/maps/embed/v1/place?key={google_api_key}&q=Hadar+HaCarmel,+Haifa&language' \
                   f'={language}'
    error = 0
    if form.is_submitted():
        route, error = make_route(form, language)
        if error == 0:
            route_string = route
    return flask.render_template('index.html', language=language, form=form, route_string=route_string, error=error)


@app.route('/favicon.ico')
def favicon():
    return flask.send_from_directory(app.static_folder, 'img/favicon.ico', mimetype='image/vnd.microsoft.icon')


def make_route(form: RouteForm, language):
    global hadar_graph
    haifa = 'Haifa'
    if language == 'he':
        haifa = 'חיפה'
    elif language == 'ar':
        haifa = 'حيفا'
    elif language == 'ru':
        haifa = 'Хайфа'
    source = geocoder.geocode(str(form.source.data) + ', ' + haifa)
    if source is None:
        return None, 1, None
    destination = geocoder.geocode(str(form.destination.data) + ', ' + haifa)
    if destination is None:
        return None, 2, None

    def node_dist(d1, d2):
        return np.sqrt(np.square(float(d1['lat']) - float(d2['lat'])) + np.square(float(d1['lon']) - float(d2['lon'])))

    def km_distance(d1, d2):
        earth_radius = 6371
        dlat = (float(d1['lat']) - float(d2['lat'])) * np.pi / 180
        dlon = (float(d1['lon']) - float(d2['lon'])) * np.pi / 180
        a = np.square(np.sin(dlat / 2))
        a += np.cos(float(d1['lat']) * np.pi / 180) * np.cos(float(d2['lat']) * np.pi / 180)\
             * np.square(np.sin(dlon / 2))
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        return c * earth_radius

    source_node = min(hadar_graph.nodes, key=lambda x: node_dist(hadar_graph.nodes[x], source.raw))
    target_node = min(hadar_graph.nodes, key=lambda x: node_dist(hadar_graph.nodes[x], destination.raw))
    source_dist = km_distance(hadar_graph.nodes[source_node], source.raw)
    target_dist = km_distance(hadar_graph.nodes[target_node], destination.raw)
    if source_dist > 0.1:
        return None, 1
    if target_dist > 0.1:
        return None, 2
    for n1, n2, attr in hadar_graph.edges(data=True):
        weight = 0
        weight += 0.001 * attr['distance']
        weight += (form.safety.data - 1) * attr['crime']
        weight += form.com_parks.data * attr['park']
        # weight += form.sport_parks.data * attr['sport']
        weight += (form.stairs.data - 1) * attr['stairs']
        weight += (form.slopes.data - 1) * attr['slope']
        hadar_graph.edges[n1, n2]['weight'] = weight
    if form.sport_route.data:
        distance = 0
        path = [source_node]
        while distance < form.route_km.data / 2:
            d = {}
            for node, attr in hadar_graph.nodes(data=True):
                d[node] = km_distance(hadar_graph.nodes[path[-1]], attr)
            d = {node: distance for node, distance in d.items()}
            next_dst = max(d, key=lambda x: d[x])
            print(next_dst, d[next_dst])
            path = nx.shortest_path(hadar_graph, source=path[-1], target=next_dst, weight='weight')
            for n1, n2 in zip(path, path[1:]):
                distance += km_distance(hadar_graph.nodes[n1], hadar_graph.nodes[n2])
                path.append(n2)
                if distance >= form.route_km.data / 2:
                    break
        while len(path) > 100:
            path = path[::2]
    else:
        path = nx.shortest_path(hadar_graph, source=source_node, target=target_node, weight='weight')
    if form.sport_parks.data:
        closest_sport_park, closest_distance = None, None
        for node in [source_node, target_node]:  # opt path
            sport_park = min([n for n in hadar_graph.nodes if hadar_graph.nodes[n]['name'] == 'Sport'],
                             key=lambda n: node_dist(hadar_graph.nodes[node], hadar_graph.nodes[n]))
            sport_distance = node_dist(hadar_graph.nodes[node], hadar_graph.nodes[sport_park])
            if closest_sport_park is None or sport_distance < closest_distance:
                closest_sport_park = sport_park
                closest_distance = sport_distance
        path1 = nx.shortest_path(hadar_graph, source=source_node, target=closest_sport_park, weight='weight')
        path2 = nx.shortest_path(hadar_graph, source=closest_sport_park, target=target_node, weight='weight')
        path = path1 + path2
    # trimmed_path = [path[0]]
    # max_path_len = 25
    # for node in path[1:]:
    #     last_node = hadar_graph.nodes[trimmed_path[-1]]
    #     if 'street_id' not in last_node or 'street_id' not in hadar_graph.nodes[node]:
    #         trimmed_path.append(node)
    #         continue
    #     if last_node['street_id'] == hadar_graph.nodes[node]['street_id']:
    #         continue
    #     trimmed_path.append(node)
    # while len(trimmed_path) > max_path_len:
    #     remove = len(trimmed_path) - max_path_len
    #     if remove > len(trimmed_path) / 2:
    #         trimmed_path = trimmed_path[::2]
    #     else:
    #         trimmed_path = [trimmed_path[0]] + random.sample(trimmed_path[1:-1], 23) + [trimmed_path[-1]]
    path_string = [f'{hadar_graph.nodes[n]["lat"]},{hadar_graph.nodes[n]["lon"]}' for n in path]
    print(path_string)
    waypoints = '|'.join(path_string[1:-1])
    return f'https://www.google.com/maps/embed/v1/directions?key={google_api_key}' \
           f'&mode=walking&origin={path_string[0]}&destination={path_string[-1]}&waypoints={waypoints}' \
           f'&center={path_string[0]}&zoom=17&language={language}', 0


if __name__ == '__main__':
    app.run()
