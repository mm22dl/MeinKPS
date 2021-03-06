#! /usr/bin/python
# -*- coding: utf-8 -*-

"""
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Title:    calculator

    Author:   David Leclerc

    Version:  0.2

    Date:     09.10.2018

    License:  GNU General Public License, Version 3
              (http://www.gnu.org/licenses/gpl.html)

    Overview: Library used to make insulin dosing decisions based on various
              treatment profiles.

    Notes:    ...

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

# LIBRARIES
import datetime
import numpy as np
import copy



# USER LIBRARIES
import fmt
import lib
import errors
import logger
import reporter



# Define instances
Logger = logger.Logger("calculator")



# CONSTANTS
BG_LOW_LIMIT       = 4.2  # (mmol/L)
BG_HIGH_LIMIT      = 8.5  # (mmol/L)
BG_VERY_HIGH_LIMIT = 11.0 # (mmol/L)
DOSE_ENACT_TIME    = 0.5  # (h)



def computeIOB(net, IDC):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        COMPUTEIOB
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        The formula to compute IOB is given by:

            IOB = S_{-DIA}^0 NET(t) * IDC(t) * dt

        where
        
        - S_{-DIA}^0: integral over time from a given number of hours in the
                      past corresponding to the duration of insulin
                      action (DIA) until now
        - NET:        net insulin profile
        - IDC:        selected insulin decay curve
        
        Since the NET is defined by steps, this integral can be decomposed such
        that:

            IOB = SUM_{t'} [NET(t') * S_{t'} IDC(t) * dt]

        where
        
        - SUM_{t'}: sum on all steps t' of NET
        - NET(t'):  step value of NET during t'
        - S_{t'}:   integral over step t'
    """

    # Initialize IOB
    IOB = 0

    # Compute IOB for each step and add it to total
    for i in range(len(net.t) - 1):
        IOB += net.y[i] * (IDC.F(net.t[i + 1]) - IDC.F(net.t[i]))

    # Return IOB
    return IOB



def computeDose(dBG, futureISF, IDC, IOB = 0):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        COMPUTEDOSE
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        Compute dose to bring back BG to target using ISF and IDC, based on the
        following formula:

            dBG = SUM_t' [ISF(t') * dIDC(t') * D]

        where

        - SUM_t':   sum on the steps of the ISF profile over the course of 
                    insulin action (next DIA hours)
        - t':       considered time step in the ISF profile
        - dBG:      desired BG variation
        - ISF(t'):  value of ISF during step t'
        - dIDC(t'): fraction of active insulin consumed during step t'
        - D:        necessary insulin dose to enable dBG.
        
        The dose can simply be taken out of the sum, since it is a constant
        (assuming the dose is an instantaneous bolus), so that:

            D = dBG / (SUM_t' [ISF(t') * dIDC(t')])
    """

    # Initialize conversion factor between dose and BG difference to target
    f = 0

    # Get number of ISF steps
    n = len(futureISF.t) - 1

    # Compute factor
    for i in range(n):

        # Get current ISF
        isf = futureISF.y[i]

        # Compute step limits (negative because IDC ranges from -DIA to 0)
        a = -futureISF.t[i]
        b = -futureISF.t[i + 1]

        # Update factor with current step
        f += isf * (IDC.f(b) - IDC.f(a))

    # Compute necessary dose (instant bolus) minus the current IOB
    dose = dBG / f - IOB

    # Return dose
    return dose



def countValidBGs(pastBG, maxAge = 30, N = 4):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        COUNTVALIDBGS
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        Count and make sure there are enough (>= N) BGs that can be considered
        valid (recent enough) for dosing decisions based on a given age (m).

        Note: it is assumed here that the end of the BG profile corresponds to
        the current time!
    """

    # Count how many BGs are not older than T
    n = np.sum(np.array(pastBG.T) > pastBG.end -
        datetime.timedelta(minutes = maxAge))

    # Check for insufficient valid BGs
    if n < N:
        raise errors.NotEnoughBGs(n, N, maxAge)

    # Return count
    return n



def computeBGI(pastBG):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        COMPUTEBGI
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        Compute dBG/dt a.k.a. BGI (mmol/L/h) using linear fit on most recent
        BGs.
    """

    # Count valid BGs
    n = countValidBGs(pastBG, 30, 4)

    # Get linear fit over last minutes
    [m, _] = np.polyfit(pastBG.t[-n:], pastBG.y[-n:], 1)

    # Return fit slope, which corresponds to BGI
    return m



def linearlyProjectBG(pastBG, dt = 0.5):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        LINEARLYPROJECTBG
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        BG projection based on expected duration dt (h) of current BGI
        (mmol/L/h).
    """

    # Info
    Logger.info("Projection time: " + str(dt) + " h")

    # Compute derivative to use when predicting future BG
    BGI = computeBGI(pastBG)

    # Get most recent BG
    BG0 = pastBG.y[-1]

    # Predict future BG
    BG = BG0 + BGI * dt

    # Return BG linear projection and BGI
    return [BG, BGI]



def computeBGDynamics(pastBG, futureBG, BGTargets, futureIOB, futureISF,
    dt = 0.5):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        COMPUTEBGDYNAMICS
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        Compute BG related dynamics.

        dt:     time period over which current BGI is expected stay constant (h)
        BG:     blood glucose (mmol/L or mg/dL)
        BGI:    variation in blood glucose (mmol/L/h or mg/dL/h)
        expBG:  expected BG after dt based on natural IOB decay (mmol/L)
        expBGI: expected BGI based on current dIOB/dt and ISF (mmol/L/h)
        IOB:    insulin-on-board (U)
        ISF:    insulin sensibility factor (mmol/L/U)
    """

    # Info
    Logger.info("Computing BG dynamics...")

    # Read expected BG after natural decay of IOB
    expectedBG = futureBG.y[-1]

    # Compute BG target by the end of insulin action
    BGTarget = np.mean(BGTargets.y[-1])

    # Compute BG assuming continuation of current BGI over dt (h)
    [shortProjectedBG, BGI] = linearlyProjectBG(pastBG, dt)

    # Compute BG variation due to IOB decay (will only work if dt is a
    # multiple of predicted BG decay's profile timestep
    shortExpectedBG = futureBG.y[futureBG.t.index(dt)]

    # Compute deviation between expected and projected BG
    shortdBG = shortProjectedBG - shortExpectedBG

    # Compute expected BGI based on IOB decay
    expectedBGI = futureIOB.dydt[0] * futureISF.y[0]

    # Compute deviation between expected and real BGI
    dBGI = BGI - expectedBGI

    # Compute eventual BG at the end of DIA
    eventualBG = expectedBG + shortdBG

    # Compute difference with BG target
    dBGTarget = BGTarget - eventualBG

    # Info about current status
    Logger.info("Current BG: " + fmt.BG(pastBG.y[-1]))
    Logger.info("Current IOB: " + fmt.IOB(futureIOB.y[0]))

    # Info about short (dt) BG projection
    Logger.info("Expected BG (dt): " + fmt.BG(shortExpectedBG))
    Logger.info("Projected BG (dt): " + fmt.BG(shortProjectedBG))
    Logger.info("dBG (dt): " + fmt.BG(shortdBG))

    # Info about long (DIA) BG projection
    Logger.info("Expected BG (DIA): " + fmt.BG(expectedBG))
    Logger.info("Eventual BG (DIA): " + fmt.BG(eventualBG))
    Logger.info("BG Target (DIA): " + fmt.BG(BGTarget))
    Logger.info("dBG to BG Target (DIA): " + fmt.BG(dBGTarget))

    # Info (BGI)
    Logger.info("Expected BGI: " + fmt.BGI(expectedBGI))
    Logger.info("Current BGI: " + fmt.BGI(BGI))
    Logger.info("dBGI: " + fmt.BGI(dBGI))

    # Return BG dynamics computations
    return {"BG": pastBG.y[-1],
            "expectedBG": expectedBG,
            "shortExpectedBG": shortExpectedBG,
            "shortProjectedBG": shortProjectedBG,
            "shortdBG": shortdBG,
            "eventualBG": eventualBG,
            "BGTarget": BGTarget,
            "dBGTarget": dBGTarget,
            "expectedBGI": expectedBGI,
            "BGI": BGI,
            "dBGI": dBGI}



def computeTB(dose, basal):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        COMPUTETB
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        Compute TB to enact given current basal and recommended insulin dose.
    """

    # Info
    Logger.debug("Computing TB to enact...")

    # Find required basal difference to enact over given time
    dB = dose / DOSE_ENACT_TIME

    # Compute TB to enact using the current basal and said required difference
    rate = basal.y[-1] + dB

    # Info
    Logger.info("Current basal: " + fmt.basal(basal.y[-1]))
    Logger.info("Required basal difference: " + fmt.basal(dB))
    Logger.info("Temporary basal to enact: " + fmt.basal(rate))
    Logger.info("Enactment time: " + str(DOSE_ENACT_TIME) + " h")

    # Return TB recommendation (in minutes)
    return {"Rate": rate, "Units": "U/h", "Duration": DOSE_ENACT_TIME * 60}



def limitTB(TB, basal, BG):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        LIMITTB
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        Limit TB recommendations based on incoming hypos or exceeding of max
        basal according to simple security computation (see under).
    """

    # Destructure TB
    rate = TB["Rate"]
    units = TB["Units"]
    duration = TB["Duration"]

    # Negative TB rate or hypo close
    if rate < 0 or BG <= BG_LOW_LIMIT:
        Logger.warning("Hypo prevention mode.")

        # Stop insulin delivery
        rate = 0

    # Positive TB
    elif rate > 0:

        # Define max basal rates
        dailyMaxBasal = max(basal.y)
        theoreticalMaxBasal = basal.max
        
        # Define factors to apply on those maxes to limit TB
        factorDailyMaxBasal = 3
        factorCurrentBasal = 4

        # High BGs
        if BG >= BG_HIGH_LIMIT:
            factorDailyMaxBasal = 4.5
            factorCurrentBasal = 6

        # Very high BGs
        if BG >= BG_VERY_HIGH_LIMIT:
            factorDailyMaxBasal = 6
            factorCurrentBasal = 8

        # Define max basal rate allowed (U/h)
        maxRate = min(factorCurrentBasal * basal.y[-1],
            factorDailyMaxBasal * dailyMaxBasal,
            theoreticalMaxBasal)

        # Info
        Logger.info("Theoretical max basal: " +
            fmt.basal(theoreticalMaxBasal))
        Logger.info(str(factorDailyMaxBasal) + "x max daily basal: " +
            fmt.basal(factorDailyMaxBasal * dailyMaxBasal))
        Logger.info(str(factorCurrentBasal) + "x current basal: " +
            fmt.basal(factorCurrentBasal * basal.y[-1]))

        # TB exceeds max
        if rate > maxRate:
            Logger.warning("TB recommendation exceeds max basal rate and has " +
                           "thus been limited. Bolus would bring BG back to " +
                           "safe range more effectively.")

            # Limit TB
            rate = maxRate

    # Return limited TB
    return {"Rate": rate, "Units": units, "Duration": duration}



def snooze(now, duration = 2):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        SNOOZE
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        Snooze enactment of TBs for a while after eating.
        TODO: take carb dynamics into consideration!
    """

    # Compute dates
    today = now.date()
    yesterday = today - datetime.timedelta(days = 1)

    # Get last carbs (no need to go further than the past 2 days)
    lastCarbs = reporter.getDatedEntries(reporter.TreatmentsReport,
        [yesterday, today], ["Carbs"])

    # Snooze criteria (no temping after eating)
    if lastCarbs:

        # Get last meal time
        lastTime = lib.formatTime(max(lastCarbs))

        # Compute elapsed time since last meal
        dt = (now - lastTime).total_seconds() / 3600.0

        # If snooze necessary
        if dt < duration:

            # Compute remaining time (m)
            t = int(round((duration - dt) * 60))

            # Info
            Logger.warning("Bolus snooze (" + str(duration) + " h). If no " +
                           "more bolus issued, high temping will resume in " +
                           str(t) + " m.")

            # Snooze
            return True

    # Do not snooze
    return False



def recommendTB(BGDynamics, basal, futureISF, IDC, IOB = 0):

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        RECOMMENDTB
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        Recommend a TB based on latest treatment information, predictions and
        security limitations.
    """

    # Info
    Logger.debug("Recommending TB...")

    # Compute necessary insulin dose to bring back eventual BG to target
    dose = computeDose(BGDynamics["dBGTarget"], futureISF, IDC, IOB)

    # Compute corresponding TB
    TB = computeTB(dose, basal)

    # Limit it
    TB = limitTB(TB, basal, BGDynamics["BG"])

    # Snoozing of temping required
    if snooze(basal.end):
        TB = None

    # Recommendation was not canceled
    if TB is not None:
        Logger.info("Recommended TB: " + fmt.TB(TB))

    # Return recommendation
    return TB



def main():

    """
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        MAIN
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    """

    # Get current time
    now = datetime.datetime(2017, 9, 1, 23, 0, 0)



# Run this when script is called from terminal
if __name__ == "__main__":
    main()