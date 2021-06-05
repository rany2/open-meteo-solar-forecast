from aiohttp import ClientSession, ClientResponseError
from dataclasses import dataclass
import logging

@dataclass
class ForecastSolarCase:

    watts: dict
    watts_hours: dict
    watts_hours_day: dict

    @staticmethod
    def from_json(item):
        attr = item["result"]
        return ForecastSolarCase(
            watts=attr["watts"],
            watts_hours=attr["watt_hours"],
            watts_hours_day=attr["watt_hours_day"]
        )

async def get_request(lat, lon, dec, az, kwp, session: ClientSession, *, source=ForecastSolarCase):
    URL = f'https://api.forecast.solar/estimate/{lat}/{lon}/{dec}/{az}/{kwp}'

    # resp = await session.get(URL)
    # data = await resp.json(content_type=None)

    # if 'error' in data:
    #     raise ClientResponseError(
    #         resp.request_info,
    #         resp.history,
    #         status=data['error']['code'],
    #         message=data['error']['message'],
    #         headers=resp.headers
    #     )

    data = {"result":{"watts":{"2021-06-04 05:17:00":0,"2021-06-04 05:31:00":2,"2021-06-04 05:45:00":13,"2021-06-04 06:00:00":24,"2021-06-04 07:00:00":89,"2021-06-04 08:00:00":244,"2021-06-04 09:00:00":447,"2021-06-04 10:00:00":700,"2021-06-04 11:00:00":950,"2021-06-04 12:00:00":585,"2021-06-04 13:00:00":642,"2021-06-04 14:00:00":663,"2021-06-04 15:00:00":620,"2021-06-04 16:00:00":536,"2021-06-04 17:00:00":430,"2021-06-04 18:00:00":305,"2021-06-04 19:00:00":184,"2021-06-04 20:00:00":82,"2021-06-04 21:02:00":13,"2021-06-04 22:03:00":0,"2021-06-05 05:16:00":0,"2021-06-05 05:31:00":2,"2021-06-05 05:45:00":13,"2021-06-05 06:00:00":22,"2021-06-05 07:00:00":73,"2021-06-05 08:00:00":164,"2021-06-05 09:00:00":281,"2021-06-05 10:00:00":397,"2021-06-05 11:00:00":503,"2021-06-05 12:00:00":592,"2021-06-05 13:00:00":659,"2021-06-05 14:00:00":698,"2021-06-05 15:00:00":659,"2021-06-05 16:00:00":572,"2021-06-05 17:00:00":464,"2021-06-05 18:00:00":333,"2021-06-05 19:00:00":197,"2021-06-05 20:00:00":89,"2021-06-05 21:02:00":13,"2021-06-05 22:04:00":0},"watt_hours":{"2021-06-04 05:17:00":0,"2021-06-04 05:31:00":0,"2021-06-04 05:45:00":4,"2021-06-04 06:00:00":9,"2021-06-04 07:00:00":97,"2021-06-04 08:00:00":341,"2021-06-04 09:00:00":788,"2021-06-04 10:00:00":1488,"2021-06-04 11:00:00":2439,"2021-06-04 12:00:00":3024,"2021-06-04 13:00:00":3666,"2021-06-04 14:00:00":4329,"2021-06-04 15:00:00":4949,"2021-06-04 16:00:00":5484,"2021-06-04 17:00:00":5914,"2021-06-04 18:00:00":6219,"2021-06-04 19:00:00":6402,"2021-06-04 20:00:00":6484,"2021-06-04 21:02:00":6499,"2021-06-04 22:03:00":6499,"2021-06-05 05:16:00":0,"2021-06-05 05:31:00":0,"2021-06-05 05:45:00":4,"2021-06-05 06:00:00":9,"2021-06-05 07:00:00":82,"2021-06-05 08:00:00":246,"2021-06-05 09:00:00":527,"2021-06-05 10:00:00":924,"2021-06-05 11:00:00":1428,"2021-06-05 12:00:00":2020,"2021-06-05 13:00:00":2678,"2021-06-05 14:00:00":3376,"2021-06-05 15:00:00":4035,"2021-06-05 16:00:00":4607,"2021-06-05 17:00:00":5072,"2021-06-05 18:00:00":5404,"2021-06-05 19:00:00":5601,"2021-06-05 20:00:00":5689,"2021-06-05 21:02:00":5702,"2021-06-05 22:04:00":5702},"watt_hours_day":{"2021-06-04":6499,"2021-06-05":5702}},"message":{"code":0,"type":"success","text":"","info":{"place":"2333 DC Leiden, Zuid-Holland, NL","timezone":"Europe/Amsterdam","distance":0.002},"ratelimit":{"period":3600,"limit":12,"remaining":10}}}

    results = []

    try:
        results.append(source.from_json(data))
    except KeyError:
        logging.getLogger(__name__).warning("Got wrong data: %s", data)
    return results